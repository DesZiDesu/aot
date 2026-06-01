# ============================================================
# ORION BOT — Standalone
# ============================================================
# คำสั่งทั้งหมดล็อกเฉพาะ Guild ID = 1498627055909339157 (Orion)
# โฮสติ้ง: SparkedHost (รัน 24/7 ไม่ต้องใช้ Flask keep-alive)
#
# วิธีใช้:
#   1) ตั้ง environment variable: DISCORD_TOKEN=<token ของบอท>
#   2) สั่งรัน: python orion_bot.py
# ============================================================

import os
import sys
import json
import time
import asyncio
import datetime
import subprocess
import random as _orion_random


# ── Auto-install (เผื่อโฮสต์ไม่ติดตั้งจาก requirements.txt อัตโนมัติ) ──
def _ensure(*packages):
    for pkg in packages:
        mod = pkg.split(">=")[0].split("[")[0].replace("-", "_")
        try:
            __import__(mod)
        except ImportError:
            print(f"[startup] installing {pkg}...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", pkg, "--quiet"],
                check=False,
            )

_ensure("discord", "openai")


import discord
from discord.ext import commands, tasks
from openai import AsyncOpenAI


# ============================================================
# CONFIG
# ============================================================

ORION_GUILD_ID        = 1498627055909339157
GUILD2_ID             = 1509774885310693480   # second guild — commands ported, separate data
import discord as _discord_early
_ORION_GUILD_OBJ = _discord_early.Object(id=ORION_GUILD_ID)
_GUILD2_OBJ      = _discord_early.Object(id=GUILD2_ID)

# Guilds ที่ slash commands ทำงานได้ (มี data dir แยก)
ALLOWED_COMMAND_GUILD_IDS = {ORION_GUILD_ID, GUILD2_ID}
ALLOWED_EXTRA_GUILD_IDS = set()   # เผื่ออนาคต (เซิร์ฟอื่นที่บอทอยู่ได้แต่ไม่มี command)

# ── Per-guild data isolation via contextvars ─────────────────
import contextvars
_current_guild_id = contextvars.ContextVar('orion_guild_id', default=ORION_GUILD_ID)


def get_data_dir() -> str:
    """คืน data dir ของ guild ปัจจุบัน (ตาม context)"""
    gid = _current_guild_id.get()
    if gid == ORION_GUILD_ID:
        return "data/orion"
    return f"data/orion_g{gid}"


def _redirect_path(path: str) -> str:
    """ถ้า context ไม่ใช่ ORION → redirect 'data/orion/...' เป็น 'data/orion_g<gid>/...'"""
    gid = _current_guild_id.get()
    if gid == ORION_GUILD_ID:
        return path
    if path.startswith("data/orion/") and not path.startswith(f"data/orion_g{gid}/"):
        return path.replace("data/orion/", f"data/orion_g{gid}/", 1)
    return path
TRETARESIA_GUILD_ID   = 1498627055909339157   # alias เดียวกัน

DATA_DIR              = "data"
ORION_DATA_DIR        = f"{DATA_DIR}/orion"
ORION_WEATHER_FILE    = f"{ORION_DATA_DIR}/weather_config.json"
ORION_PLAYERS_FILE    = f"{ORION_DATA_DIR}/players.json"
TRETARESIA_QUEST_FILE = f"{DATA_DIR}/tretaresia_quests.json"
TR_PLAYERS_FILE       = f"{DATA_DIR}/tretaresia_players.json"

ORION_WEATHER_CYCLE   = 32 * 3600   # 32 ชั่วโมง

# AI สำหรับ TRETARESIA Quest
TR_API_BASE  = os.environ.get("TR_API_BASE",  "https://one.xiaweiliang.cn/v1")
TR_API_KEY   = os.environ.get("TR_API_KEY",   "sk-LisBDSYhws2VyD9GsxKNNEcS76IzT9JnycNtVOZUSK0u5wt0")
TR_MODEL     = os.environ.get("TR_MODEL",     "gemini-3.1-pro-preview-maxthinking-search")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ORION_DATA_DIR, exist_ok=True)


# ============================================================
# BOT SETUP
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=['?'], intents=intents, help_command=None)
tr_client = AsyncOpenAI(api_key=TR_API_KEY, base_url=TR_API_BASE)


# ============================================================
# JSON helpers
# ============================================================

def load_json(path: str, default=None):
    if default is None:
        default = {}
    path = _redirect_path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f"[load_json] {path}: {e}")
        return default


def save_json(path, data):
    path = _redirect_path(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_orion_guild(ctx) -> bool:
    g = getattr(ctx, "guild", None)
    return g is not None and g.id == ORION_GUILD_ID


# ── Settings (per-command public/ephemeral toggle) ───────────
SETTINGS_FILE = f"{ORION_DATA_DIR}/settings.json"

# Commands ที่อนุญาตให้ admin toggle ผ่าน /setting
TOGGLEABLE_COMMANDS = [
    ("orion",         "ดูโปรไฟล์ตัวละคร"),
    ("ไอเทม",         "ดูกระเป๋าเงิน + ไอเทมของตัวเอง"),
    ("คลังไอเทม",     "ดูไอเทมทั้งหมดในเซิร์ฟ"),
    ("เงิน",          "ดูเงินตัวเอง"),
    ("เช็คเงิน",      "ดูเงินคนอื่น"),
    ("เช็คของ",       "ดูของคนอื่น"),
    ("โอนเงิน",       "โอนเงินให้คนอื่น"),
    ("โอนของ",        "โอนของให้คนอื่น"),
    ("คราฟ",          "คราฟไอเทม"),
    ("ฝึกสกิล",       "ฝึกฝนเรียนสกิล"),
    ("หาของ",         "ออกหาของ"),
    ("guild",         "ระบบกิลด์"),
    ("familia",       "ระบบ Familia"),
    ("ดูประมูล",      "ดูรายการประมูล"),
    ("ร้าน",          "เปิดร้านค้า"),
    ("คูปอง",         "ดูคูปอง"),
    ("บทบาท",         "ดูระบบบทบาท"),
    ("คาสิโน",        "เล่นคาสิโน solo"),
    ("คาสิโนห้อง",    "คาสิโนห้องผู้เล่น"),
    ("กาชา",          "เปิดตู้กาชา"),
    ("พื้นที่",        "ดูเขตในระบบ"),
    ("สภาพอากาศ",     "ดูสภาพอากาศ"),
]


def load_settings() -> dict:
    return load_json(SETTINGS_FILE, {"public_commands": []})


def save_settings(s: dict):
    save_json(SETTINGS_FILE, s)


def _eph(cmd_name: str) -> bool:
    """True = ephemeral (เห็นเฉพาะคุณ), False = public (เห็นทุกคน)"""
    return cmd_name not in load_settings().get("public_commands", [])


# ── Emoji sanitizer ──────────────────────────────────────────
# ปัญหา: Discord SelectOption.emoji ห้ามรับ string ที่ไม่ใช่ emoji จริง
# (เช่น "fire", "ไฟ", "Aurum") — จะ throw Invalid Form Body 50035
# fn นี้คืนเฉพาะ emoji ที่ Discord ยอมรับ: unicode emoji หรือ <:name:id>
import re as _re_emoji
import unicodedata as _ud
_CUSTOM_EMOJI_RE = _re_emoji.compile(r"^<a?:[A-Za-z0-9_]+:\d+>$")


# ── UI helpers (ReQuest-style menu) ──────────────────────────
def make_menu_embed(title: str, sections: list, color: int = 0x5865f2) -> discord.Embed:
    """ReQuest-style embed: title + แต่ละ section เป็นข้อความบอกสั้นๆ
    sections = [(desc_text,), ...] หรือ [(name, desc), ...]"""
    embed = discord.Embed(title=title, color=color)
    parts = []
    for s in sections:
        if isinstance(s, tuple) and len(s) >= 2:
            parts.append(f"**{s[0]}**\n{s[1]}")
        elif isinstance(s, tuple):
            parts.append(s[0])
        else:
            parts.append(str(s))
    embed.description = "\n\n".join(parts)
    return embed


class DoneBtn(discord.ui.Button):
    """ปุ่ม Done — ปิดเมนู ephemeral"""
    def __init__(self, row: int = 0):
        super().__init__(label="Done", style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, ix: discord.Interaction):
        try:
            await ix.response.edit_message(content="✓", embed=None, view=None)
        except Exception:
            await ix.response.defer()


def _safe_emoji(s, default="✨"):
    """รับ string → คืน emoji ที่ปลอดภัยสำหรับ SelectOption (หรือ default)
    block ทุกอย่างที่เป็น Letter หรือ Number — รวมตัวอักษรไทย/อังกฤษ/เลข"""
    if not s or not isinstance(s, str):
        return default
    s = s.strip()
    if not s:
        return default
    # custom server emoji format
    if _CUSTOM_EMOJI_RE.match(s):
        return s
    # ยาวเกิน 12 → ไม่ใช่ emoji เดี่ยว (ZWJ sequence ปกติไม่เกินนี้)
    if len(s) > 12:
        return default
    # check Unicode category — Letter/Number ทั้งหมดไม่ใช่ emoji
    # L = Letter (Lu, Ll, Lt, Lm, Lo), N = Number (Nd, Nl, No)
    for c in s:
        if c in (" ", "‍", "️"):   # space / ZWJ / VS16 — emoji modifiers
            continue
        cat = _ud.category(c)
        if cat[0] in ("L", "N", "P", "C"):   # Letter, Number, Punctuation, Control
            return default
    return s


# ============================================================
# HELP CATEGORIES (ใช้สำหรับ allowlist)
# ============================================================

HELP_CATEGORIES: dict = {}


# ══════════════════════════════════════════════════════════════
# ██  TRETARESIA — ระบบเควสต์ AI สำหรับเซิร์ฟ Orion City
# ══════════════════════════════════════════════════════════════

def _load_tr_quests() -> dict:
    try:
        with open(TRETARESIA_QUEST_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_tr_quests(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TRETARESIA_QUEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_tr_players() -> dict:
    try:
        with open(TR_PLAYERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_tr_players(data: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TR_PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


_TR_SYSTEM_PROMPT = """
# MASTER — Quest Narrator of TRETARESIA
คุณคือ Master ผู้บรรยายฉากและดำเนินเรื่องในโลก TRETARESIA ตอบเป็นภาษาไทยเท่านั้น

═══════════════════════════════════
## กฎเหล็ก (Anti-User Rule)
═══════════════════════════════════
- ห้ามพิมพ์แทนผู้เล่น ห้ามกำหนดการกระทำ ความคิด ความรู้สึก หรือคำพูดของผู้เล่นโดยเด็ดขาด
- บรรยายเฉพาะสิ่งที่ผู้เล่นมองเห็น ได้ยิน ได้กลิ่น สัมผัสได้จากภายนอก
- จบทุก response ในจุดที่ผู้เล่นต้องตัดสินใจ — อย่าตัดสินใจแทน
- ห้ามใช้ single quote (' ') ในการเขียนบทพูด ใช้ double quote (" ") เสมอ

═══════════════════════════════════
## โลก TRETARESIA — Orion City
═══════════════════════════════════
โลกแฟนตาซีที่ทวยเทพจากทุกตำนานสละบัลลังก์สวรรค์ ลงมาใช้ชีวิตร่วมกับมนุษย์เมื่อ 300 ปีก่อน
กฎเดียวที่พวกเขาตั้งไว้: "พลังอันแท้จริงของเทพเป็นสิ่งต้องห้ามโดยเด็ดขาด"
ศูนย์กลางคือเมือง Orion City — เต็มไปด้วย Familia (กลุ่มที่เทพเป็นหัวหน้า) ที่มีวาระซ่อนเร้นของตัวเอง

**Familia** = หน่วยครอบครัวที่เทพสร้าง มีสมาชิกได้สูงสุด 20 คน แต่ละ Familia มีบทบาท อำนาจ และเป้าหมายต่างกัน

**Artifact** = สิ่งประดิษฐ์ที่สลักพลังพิเศษไว้ มนุษย์ใช้แทนพลังเทพได้ แต่ทุก Artifact มีผลเสียแฝง — ยิ่งทรงพลังยิ่งแพงราคา

**Origin** = พลังเฉพาะตัวของตัวละครที่มีพลังพิเศษ (ไม่ใช่เวทมนตร์ทั่วไป) กำหนดโดยแก่นตัวตนและอุดมการณ์

**Physical Scale**: E (มนุษย์ปกติ) → D → C → B → A → S → SS → SSS → EX (นอกกฎของโลก)

ธีมหลัก: ชีวิตประจำวัน / การเมืองและอำนาจระหว่าง Familia / ความลับของทวยเทพ / การสูญเสียและการเติบโต

═══════════════════════════════════
## สไตล์การบรรยาย
═══════════════════════════════════
- ใช้ภาษาไทยที่ไพเราะ มีจังหวะ สร้างบรรยากาศด้วยประสาทสัมผัสทั้งห้า
- NPC มีอุดมการณ์ แรงจูงใจ และวาระซ่อนเร้นของตัวเอง ไม่ใช่แค่ตอบสนองผู้เล่น
- สลับ subvert trope เสมอ — หักมุมเมื่อผู้อ่านคาดไม่ถึง
- ใส่ผลของการกระทำอย่างสมจริง (ต่อสู้แล้วเจ็บจริง ทำลายข้าวของแล้วมีคนรู้เห็น)
- ฉากต่อสู้ต้องมีพลวัต — สภาพแวดล้อมเปลี่ยน ศัตรูปรับกลยุทธ์ ไม่มีการต่อสู้แบบ "ตีซ้ำๆ"
- อ้างอิง Physical Scale เมื่อมีการต่อสู้เพื่อความสมเหตุสมผล

═══════════════════════════════════
## กฎ NPC
═══════════════════════════════════
- NPC ทำอะไรได้อิสระโดยไม่รอผู้เล่น — มีชีวิตของตัวเอง
- NPC มีชื่อที่ไม่ใช่ชื่อไทยจริง (randomize ให้เข้ากับโลก)
- NPC ที่เป็นเทพมีอำนาจและความรู้สึกเหมือนมนุษย์ — ไม่สมบูรณ์แบบ มีความกลัวและความลับ
- Familia ต่างๆ มีความขัดแย้งซ่อนอยู่เสมอ แม้หน้าสงบ

═══════════════════════════════════
## กฎการเล่นหลายคน (Multi-Player)
═══════════════════════════════════
- ผู้เล่นแต่ละคนจะถูกระบุด้วยชื่อตัวละครก่อนบทพูด เช่น "Elias: ฉันเดินเข้าไป"
- บรรยายให้เห็นชัดว่าใครอยู่ในฉากและใครทำอะไร — อย่าปนบทบาทของแต่ละคน
- NPC และสภาพแวดล้อมตอบสนองต่อการกระทำของผู้เล่นแต่ละคนอย่างเป็นธรรมชาติ
- ถ้าผู้เล่นหลายคนอยู่ในฉาก ให้ผลักดันเรื่องราวโดยคำนึงถึงทุกคน
- ห้ามบรรยายผลของการกระทำที่ผู้เล่นยังไม่ได้ทำ (รอแต่ละคนพิมพ์เอง)
- เมื่อมีผู้เล่นหลายคน ให้ฉากดำเนินต่อได้แม้ไม่ครบทุกคนตอบ
- ข้อมูลตัวละคร ([ข้อมูลตัวละคร:...]) ที่แนบมาในแต่ละ turn คือข้อมูลสำหรับคุณเท่านั้น ห้ามอ่านออกมาในบทบรรยาย
""".strip()


async def _tr_ai_call(history: list) -> str:
    try:
        response = await tr_client.chat.completions.create(
            model=TR_MODEL,
            messages=[{"role": "system", "content": _TR_SYSTEM_PROMPT}] + history,
            max_tokens=1500,
            temperature=0.9,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"##TR_ERROR## {e}"


def _build_tr_profile_embed(data: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title=f"🪞  {data.get('char_name', member.display_name)}",
        color=0xc9a84c,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="เผ่าพันธุ์ & อายุ", value=data.get("race_age", "—"), inline=True)
    embed.add_field(name="​", value="​", inline=True)
    embed.add_field(name="​", value="​", inline=True)
    embed.add_field(name="รูปลักษณ์ภายนอก", value=data.get("appearance", "—"), inline=False)
    if data.get("outfit"):
        embed.add_field(name="การแต่งกาย", value=data["outfit"], inline=False)
    if data.get("artifact_visible"):
        embed.add_field(name="⚙️ Artifact (ที่มองเห็นได้)", value=data["artifact_visible"], inline=False)
    if data.get("artifact_hidden"):
        embed.add_field(name="🔒 Artifact (ที่ซ่อนอยู่ — AI รู้แต่ไม่บรรยาย)", value=data["artifact_hidden"], inline=False)
    if data.get("extra_note"):
        embed.add_field(name="จุดสังเกต", value=data["extra_note"], inline=False)
    embed.set_footer(text="TRETARESIA — Orion City Character Profile")
    return embed


def _build_tr_player_context(uid: str, players: dict) -> str:
    data = players.get(uid)
    if not data:
        return ""
    lines = [
        f"[ข้อมูลตัวละคร: {data.get('char_name','?')} | {data.get('race_age','?')}]",
        f"[ลักษณะภายนอกที่มองเห็นได้: {data.get('appearance','')}]",
    ]
    if data.get("outfit"):
        lines.append(f"[การแต่งกายที่มองเห็นได้: {data['outfit']}]")
    if data.get("artifact_visible"):
        lines.append(f"[Artifact ที่มองเห็นได้บนตัว: {data['artifact_visible']}]")
    if data.get("artifact_hidden"):
        lines.append(f"[Artifact ที่ซ่อนอยู่ (AI รู้แต่ห้ามบรรยายให้ผู้อื่นรู้ เว้นแต่ถูกเปิดเผยใน RP): {data['artifact_hidden']}]")
    if data.get("extra_note"):
        lines.append(f"[จุดสังเกตอื่นๆ ภายนอก: {data['extra_note']}]")
    return "\n".join(lines)


# ── Quest Creation Modal ────────────────────────────────────────
class TRQuestModal(discord.ui.Modal, title="⚔️ สร้างภารกิจ — Orion City"):
    channel_id_input = discord.ui.TextInput(
        label="Channel ID (ห้องสร้างเธรด)",
        placeholder="วาง Channel ID (ตัวเลข)",
        required=True, max_length=25,
    )
    location = discord.ui.TextInput(
        label="สถานที่ใน Orion City",
        placeholder="เช่น ตลาดกลางคืน / หอคอย Familia Ares",
        required=True, max_length=150,
    )
    mission = discord.ui.TextInput(
        label="ภารกิจ / เหตุการณ์",
        style=discord.TextStyle.paragraph,
        placeholder="อธิบายภารกิจหรือเหตุการณ์ที่เกิดขึ้น",
        required=True, max_length=600,
    )
    extra = discord.ui.TextInput(
        label="รายละเอียดเพิ่มเติม (ไม่บังคับ)",
        style=discord.TextStyle.paragraph,
        placeholder="เช่น มีพยาน / กลางดึก / มีร่องรอย Aura",
        required=False, max_length=400,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            cid = int(self.channel_id_input.value.strip())
            channel = interaction.guild.get_channel(cid)
            if channel is None:
                channel = await interaction.guild.fetch_channel(cid)
        except Exception:
            await interaction.followup.send("❌ ไม่พบ Channel ID นี้ในเซิร์ฟ", ephemeral=True)
            return

        desc_parts = [f"📍 **สถานที่:** {self.location.value}", f"\n{self.mission.value}"]
        if self.extra.value:
            desc_parts.append(f"\n\n*{self.extra.value}*")
        embed = discord.Embed(
            title=f"📜 ภารกิจใหม่ — {self.location.value}",
            description="\n".join(desc_parts),
            color=0xd4af37,
        )
        embed.set_author(name=f"GM: {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        embed.set_footer(text="TRETARESIA — Orion City | พิมพ์ในเธรดเพื่อเริ่มผจญภัย")

        msg = await channel.send(embed=embed)
        thread_name = f"📜 {self.location.value}"[:80]
        thread = await msg.create_thread(name=thread_name, auto_archive_duration=10080)

        quests = _load_tr_quests()
        quests[str(thread.id)] = {
            "status": "active",
            "title": self.location.value,
            "created_by": str(interaction.user.id),
            "team_ids": [],
            "history": [],
        }
        _save_tr_quests(quests)

        opening_prompt = (
            f"สถานที่: {self.location.value}\n"
            f"ภารกิจ: {self.mission.value}\n"
            + (f"รายละเอียดเพิ่มเติม: {self.extra.value}\n" if self.extra.value else "")
            + "\nบรรยายฉากเปิดของภารกิจนี้ ให้ผู้เล่นรู้สึกถึงบรรยากาศ Orion City ก่อนเริ่มผจญภัย"
        )
        history = [{"role": "user", "content": opening_prompt}]
        async with thread.typing():
            reply = await _tr_ai_call(history)

        if reply.startswith("##TR_ERROR##"):
            await thread.send(f"⚠️ AI error: `{reply[13:]}`")
        else:
            quests[str(thread.id)]["history"] = history + [{"role": "assistant", "content": reply}]
            _save_tr_quests(quests)
            for chunk in [reply[i:i+1900] for i in range(0, len(reply), 1900)]:
                await thread.send(chunk)

        join_embed = discord.Embed(
            description=(
                "กดปุ่มด้านล่าง **หรือ** พิมพ์ `?trเข้าร่วม` เพื่อเข้าร่วมภารกิจนี้\n"
                "*เฉพาะผู้เล่นที่เข้าร่วมแล้วเท่านั้นที่สามารถโต้ตอบกับ AI ได้*"
            ),
            color=0x2c2f33,
        )
        await thread.send(embed=join_embed, view=TRJoinView(str(thread.id)))
        await interaction.followup.send(f"✅ สร้างภารกิจแล้วที่ {thread.mention}", ephemeral=True)


class TRJoinView(discord.ui.View):
    def __init__(self, thread_id: str):
        super().__init__(timeout=None)
        self.thread_id = thread_id

    @discord.ui.button(label="⚔️ เข้าร่วมภารกิจ", style=discord.ButtonStyle.success, custom_id="tr_join_quest")
    async def btn_join(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        quests = _load_tr_quests()
        q = quests.get(self.thread_id)
        if not q:
            await interaction.response.send_message("❌ ไม่พบข้อมูลภารกิจ", ephemeral=True); return
        if q.get("status") != "active":
            await interaction.response.send_message("❌ ภารกิจนี้ปิดแล้ว", ephemeral=True); return
        if uid in q.get("team_ids", []):
            await interaction.response.send_message("✅ คุณเข้าร่วมภารกิจนี้แล้ว", ephemeral=True); return
        q.setdefault("team_ids", []).append(uid)
        _save_tr_quests(quests)
        tr_players = _load_tr_players()
        char_name = tr_players.get(uid, {}).get("char_name") or interaction.user.display_name
        await interaction.response.send_message(
            embed=discord.Embed(
                description=(
                    f"**{char_name}** เข้าร่วมภารกิจแล้ว ⚔️\n"
                    f"สมาชิกในทีม: **{len(q['team_ids'])}** คน\n\n"
                    "*พิมพ์ข้อความในเธรดนี้เพื่อโต้ตอบกับ AI*"
                ),
                color=0x2ecc71,
            )
        )

    @discord.ui.button(label="🚪 ออกจากภารกิจ", style=discord.ButtonStyle.danger, custom_id="tr_leave_quest")
    async def btn_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        uid = str(interaction.user.id)
        quests = _load_tr_quests()
        q = quests.get(self.thread_id)
        if not q or uid not in q.get("team_ids", []):
            await interaction.response.send_message("❌ คุณไม่ได้อยู่ในภารกิจนี้", ephemeral=True); return
        q["team_ids"].remove(uid)
        _save_tr_quests(quests)
        tr_players = _load_tr_players()
        char_name = tr_players.get(uid, {}).get("char_name") or interaction.user.display_name
        await interaction.response.send_message(
            embed=discord.Embed(description=f"**{char_name}** ออกจากภารกิจแล้ว", color=0xe74c3c)
        )

    @discord.ui.button(label="👥 ดูสมาชิก", style=discord.ButtonStyle.secondary, custom_id="tr_list_members")
    async def btn_members(self, interaction: discord.Interaction, button: discord.ui.Button):
        quests = _load_tr_quests()
        q = quests.get(self.thread_id)
        if not q:
            await interaction.response.send_message("❌ ไม่พบข้อมูลภารกิจ", ephemeral=True); return
        tr_players = _load_tr_players()
        team = q.get("team_ids", [])
        if not team:
            await interaction.response.send_message("*(ยังไม่มีผู้เล่นเข้าร่วม)*", ephemeral=True); return
        lines = []
        for tid in team:
            char_name = tr_players.get(tid, {}).get("char_name") or f"<@{tid}>"
            race = tr_players.get(tid, {}).get("race_age", "")
            lines.append(f"⚔️ **{char_name}** {f'— {race}' if race else ''}")
        embed = discord.Embed(
            title=f"👥 สมาชิกในภารกิจ ({len(team)} คน)",
            description="\n".join(lines),
            color=0xd4af37,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.command(name="trเข้าร่วม", aliases=["trjoin", "jointr"])
async def tr_join_cmd(ctx):
    if not ctx.guild or ctx.guild.id != TRETARESIA_GUILD_ID:
        return
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("❌ ใช้คำสั่งนี้ภายในเธรดภารกิจเท่านั้น", delete_after=5); return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    uid = str(ctx.author.id)
    quests = _load_tr_quests()
    q = quests.get(str(ctx.channel.id))
    if not q:
        await ctx.send("❌ ไม่พบข้อมูลภารกิจในเธรดนี้", delete_after=5); return
    if q.get("status") != "active":
        await ctx.send("❌ ภารกิจนี้ปิดแล้ว", delete_after=5); return
    if uid in q.get("team_ids", []):
        await ctx.send("✅ คุณเข้าร่วมภารกิจนี้แล้ว", delete_after=5); return
    q.setdefault("team_ids", []).append(uid)
    _save_tr_quests(quests)
    tr_players = _load_tr_players()
    char_name = tr_players.get(uid, {}).get("char_name") or ctx.author.display_name
    await ctx.send(embed=discord.Embed(
        description=(
            f"**{char_name}** เข้าร่วมภารกิจแล้ว ⚔️\n"
            f"สมาชิกในทีม: **{len(q['team_ids'])}** คน\n\n"
            "*พิมพ์ข้อความในเธรดนี้เพื่อโต้ตอบกับ AI*"
        ),
        color=0x2ecc71,
    ))


@bot.command(name="trออก", aliases=["trleave", "leavetr"])
async def tr_leave_cmd(ctx):
    if not ctx.guild or ctx.guild.id != TRETARESIA_GUILD_ID:
        return
    if not isinstance(ctx.channel, discord.Thread):
        await ctx.send("❌ ใช้คำสั่งนี้ภายในเธรดภารกิจเท่านั้น", delete_after=5); return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    uid = str(ctx.author.id)
    quests = _load_tr_quests()
    q = quests.get(str(ctx.channel.id))
    if not q or uid not in q.get("team_ids", []):
        await ctx.send("❌ คุณไม่ได้อยู่ในภารกิจนี้", delete_after=5); return
    q["team_ids"].remove(uid)
    _save_tr_quests(quests)
    tr_players = _load_tr_players()
    char_name = tr_players.get(uid, {}).get("char_name") or ctx.author.display_name
    await ctx.send(embed=discord.Embed(description=f"**{char_name}** ออกจากภารกิจแล้ว", color=0xe74c3c))


# ── Admin Panel ──
class TRChangeModelModal(discord.ui.Modal, title="🌐 เปลี่ยน AI Model"):
    model_input = discord.ui.TextInput(
        label="ชื่อ Model",
        placeholder="เช่น gemini-3.1-pro-preview-maxthinking-search",
        default="gemini-3.1-pro-preview-maxthinking-search",
        max_length=80,
    )

    async def on_submit(self, interaction: discord.Interaction):
        global TR_MODEL
        old_model = TR_MODEL
        TR_MODEL = self.model_input.value.strip()
        embed = discord.Embed(title="🌐 เปลี่ยน AI Model แล้ว", color=0x3498db)
        embed.add_field(name="เดิม", value=f"`{old_model}`", inline=False)
        embed.add_field(name="ใหม่", value=f"`{TR_MODEL}`", inline=False)
        embed.set_footer(text="TRETARESIA — การเปลี่ยนนี้จะหายเมื่อรีสตาร์ทบอท")
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TRAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="⚔️ สร้างภารกิจ", style=discord.ButtonStyle.danger, row=0)
    async def btn_create_quest(self, interaction, button):
        await interaction.response.send_modal(TRQuestModal())

    @discord.ui.button(label="📜 ปิดภารกิจ", style=discord.ButtonStyle.secondary, row=0)
    async def btn_end_quest(self, interaction, button):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ ใช้ได้เฉพาะในเธรดภารกิจ", ephemeral=True); return
        quests = _load_tr_quests()
        ckey = str(interaction.channel.id)
        if ckey not in quests:
            await interaction.response.send_message("❌ ไม่พบข้อมูลภารกิจในเธรดนี้", ephemeral=True); return
        quests[ckey]["status"] = "ended"
        _save_tr_quests(quests)
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📜 ภารกิจสิ้นสุดแล้ว",
                description="GM ปิดภารกิจนี้แล้ว ขอบคุณทุกคนที่ร่วมผจญภัยใน Orion City",
                color=0x95a5a6,
            ).set_footer(text="TRETARESIA — Orion City")
        )

    @discord.ui.button(label="📊 สถานะภารกิจ", style=discord.ButtonStyle.primary, row=0)
    async def btn_quest_status(self, interaction, button):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ ใช้ได้เฉพาะในเธรดภารกิจ", ephemeral=True); return
        quests = _load_tr_quests()
        q = quests.get(str(interaction.channel.id))
        if not q:
            await interaction.response.send_message("❌ ไม่พบข้อมูลภารกิจ", ephemeral=True); return
        turns = len([h for h in q.get("history", []) if h["role"] == "user"])
        members = q.get("team_ids", [])
        embed = discord.Embed(title=f"📊 {q.get('title','?')}", color=0xd4af37)
        embed.add_field(name="สถานะ", value="🟢 ดำเนินการ" if q.get("status") == "active" else "⚫ ปิดแล้ว", inline=True)
        embed.add_field(name="รอบสนทนา", value=str(turns), inline=True)
        embed.add_field(name="นักผจญภัย", value=str(len(members)), inline=True)
        embed.add_field(name="ผู้สร้าง", value=f"<@{q.get('created_by','?')}>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔄 รีเซ็ต AI", style=discord.ButtonStyle.secondary, row=1)
    async def btn_reset_ai(self, interaction, button):
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message("❌ ใช้ได้เฉพาะในเธรดภารกิจ", ephemeral=True); return
        quests = _load_tr_quests()
        ckey = str(interaction.channel.id)
        if ckey not in quests:
            await interaction.response.send_message("❌ ไม่พบข้อมูลภารกิจ", ephemeral=True); return
        quests[ckey]["history"] = []
        _save_tr_quests(quests)
        await interaction.response.send_message("🔄 ล้าง history AI ของภารกิจนี้แล้ว", ephemeral=True)

    @discord.ui.button(label="🌐 เปลี่ยน Model", style=discord.ButtonStyle.secondary, row=1)
    async def btn_change_model(self, interaction, button):
        await interaction.response.send_modal(TRChangeModelModal())


@bot.command(name="orionadmin", aliases=["trpanel", "tradmin"])
async def tr_admin_panel(ctx):
    if not ctx.guild or ctx.guild.id != TRETARESIA_GUILD_ID:
        return
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.send("❌ ต้องมีสิทธิ์ Manage Messages ขึ้นไป", delete_after=5); return
    embed = discord.Embed(
        title="⚔️  TRETARESIA — แผงควบคุม GM",
        description=(
            "จัดการภารกิจและโลก **Orion City** ผ่านปุ่มด้านล่าง\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌐 **AI Model:** `{TR_MODEL}`\n"
            "🗺️ **โลก:** TRETARESIA — Orion City\n"
            "⚙️ **สถานะ:** พร้อมรับภารกิจ"
        ),
        color=0xd4af37,
    )
    embed.set_footer(text="TRETARESIA — GM Control Panel | Classified")
    await ctx.send(embed=embed, view=TRAdminView())


# ── TRETARESIA Player Profile ───────────────────────────────────
class TRCharModal(discord.ui.Modal, title="🪞 ตัวละคร — รูปลักษณ์"):
    char_name = discord.ui.TextInput(label="ชื่อตัวละคร", placeholder="เช่น Elias Vorn / Serana", max_length=50, required=True)
    race_age = discord.ui.TextInput(label="เผ่าพันธุ์ & อายุ", placeholder="เช่น มนุษย์ อายุ 19", max_length=80, required=True)
    appearance = discord.ui.TextInput(label="รูปลักษณ์ภายนอก", style=discord.TextStyle.paragraph, placeholder="ผม ดวงตา ส่วนสูง รูปร่าง รอยแผลเป็น", max_length=500, required=True)
    outfit = discord.ui.TextInput(label="ชุด / การแต่งกาย", style=discord.TextStyle.paragraph, placeholder="เช่น เสื้อคลุมสีเทา กางเกงหนัง", max_length=300, required=False)
    extra_note = discord.ui.TextInput(label="จุดสังเกต (ไม่บังคับ)", placeholder="เช่น ท่าทางเงียบขรึม รอยสักที่คอ", max_length=200, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        players = _load_tr_players()
        prev = players.get(uid, {})
        players[uid] = {
            **prev,
            "char_name": self.char_name.value.strip(),
            "race_age":  self.race_age.value.strip(),
            "appearance": self.appearance.value.strip(),
            "outfit":     self.outfit.value.strip(),
            "extra_note": self.extra_note.value.strip(),
        }
        _save_tr_players(players)
        embed = _build_tr_profile_embed(players[uid], interaction.user)
        await interaction.response.send_message("✅ บันทึกข้อมูลรูปลักษณ์แล้ว", embed=embed, ephemeral=True)


class TRArtifactModal(discord.ui.Modal, title="⚙️ ตัวละคร — Artifact"):
    artifact_visible = discord.ui.TextInput(label="Artifact ที่มองเห็นได้ (AI บรรยายได้)", style=discord.TextStyle.paragraph, placeholder="สิ่งที่คนอื่นมองเห็นได้ เช่น กริชแปลกที่เอว", max_length=400, required=False)
    artifact_hidden  = discord.ui.TextInput(label="Artifact ซ่อน (AI รู้ แต่ไม่บรรยาย)",   style=discord.TextStyle.paragraph, placeholder="ซ่อนในร่างกาย/กระเป๋า เปิดเผยใน RP เอง",     max_length=400, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        players = _load_tr_players()
        if uid not in players:
            await interaction.response.send_message("❌ กรุณาตั้งค่ารูปลักษณ์ก่อน (กดปุ่ม 🪞 แก้ไขตัวละคร)", ephemeral=True); return
        players[uid]["artifact_visible"] = self.artifact_visible.value.strip()
        players[uid]["artifact_hidden"]  = self.artifact_hidden.value.strip()
        _save_tr_players(players)
        embed = _build_tr_profile_embed(players[uid], interaction.user)
        await interaction.response.send_message("✅ บันทึก Artifact แล้ว", embed=embed, ephemeral=True)


class TRPlayerMenuView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ เมนูนี้ไม่ใช่ของคุณ", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🪞 แก้ไขตัวละคร", style=discord.ButtonStyle.primary, row=0)
    async def btn_edit_char(self, interaction, button):
        uid = str(interaction.user.id)
        players = _load_tr_players()
        modal = TRCharModal()
        data = players.get(uid, {})
        if data.get("char_name"):  modal.char_name.default  = data["char_name"]
        if data.get("race_age"):   modal.race_age.default   = data["race_age"]
        if data.get("appearance"): modal.appearance.default = data["appearance"]
        if data.get("outfit"):     modal.outfit.default     = data["outfit"]
        if data.get("extra_note"): modal.extra_note.default = data["extra_note"]
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⚙️ แก้ไข Artifact", style=discord.ButtonStyle.secondary, row=0)
    async def btn_edit_artifact(self, interaction, button):
        uid = str(interaction.user.id)
        players = _load_tr_players()
        modal = TRArtifactModal()
        data = players.get(uid, {})
        if data.get("artifact_visible"): modal.artifact_visible.default = data["artifact_visible"]
        if data.get("artifact_hidden"):  modal.artifact_hidden.default  = data["artifact_hidden"]
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📋 ดูโปรไฟล์", style=discord.ButtonStyle.success, row=0)
    async def btn_view_profile(self, interaction, button):
        uid = str(interaction.user.id)
        data = _load_tr_players().get(uid)
        if not data:
            await interaction.response.send_message("❌ ยังไม่มีข้อมูลตัวละคร กดปุ่ม 🪞 แก้ไขตัวละคร เพื่อเริ่มต้น", ephemeral=True); return
        embed = _build_tr_profile_embed(data, interaction.user)
        await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.command(name="trเมนู", aliases=["trmenu", "trme", "orionme"])
async def tr_player_menu(ctx):
    if not ctx.guild or ctx.guild.id != TRETARESIA_GUILD_ID:
        return
    try:
        await ctx.message.delete()
    except Exception:
        pass
    embed = discord.Embed(
        title="⚔️  เมนูตัวละคร — Orion City",
        description=(
            "จัดการข้อมูลตัวละครของคุณใน **TRETARESIA**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "🪞 **แก้ไขตัวละคร** — รูปลักษณ์ภายนอก ชุด จุดสังเกต\n"
            "⚙️ **แก้ไข Artifact** — ของที่มองเห็น / ของที่ซ่อนอยู่\n"
            "📋 **ดูโปรไฟล์** — ดูข้อมูลตัวละครของตัวเอง\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*AI จะรู้ข้อมูลทั้งหมด แต่บรรยายเฉพาะสิ่งที่มองเห็นได้ภายนอก*"
        ),
        color=0xd4af37,
    )
    embed.set_footer(text="TRETARESIA — Orion City | เมนูนี้หมดอายุใน 2 นาที")
    await ctx.send(embed=embed, view=TRPlayerMenuView(ctx.author.id))


@bot.command(name="trดูโปรไฟล์", aliases=["trviewprofile", "trprofile"])
async def tr_view_other_profile(ctx, member: discord.Member = None):
    if not ctx.guild or ctx.guild.id != TRETARESIA_GUILD_ID:
        return
    target = member or ctx.author
    data = _load_tr_players().get(str(target.id))
    if not data:
        await ctx.send(f"{'คุณ' if target == ctx.author else target.display_name}ยังไม่มีข้อมูลตัวละคร", delete_after=6); return
    show_hidden = target == ctx.author
    embed = discord.Embed(title=f"🪞  {data.get('char_name', target.display_name)}", color=0xc9a84c)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="เผ่าพันธุ์ & อายุ", value=data.get("race_age", "—"), inline=False)
    embed.add_field(name="รูปลักษณ์ภายนอก", value=data.get("appearance", "—"), inline=False)
    if data.get("outfit"):           embed.add_field(name="การแต่งกาย", value=data["outfit"], inline=False)
    if data.get("artifact_visible"): embed.add_field(name="⚙️ Artifact (ที่มองเห็นได้)", value=data["artifact_visible"], inline=False)
    if show_hidden and data.get("artifact_hidden"):
        embed.add_field(name="🔒 Artifact (ซ่อนอยู่)", value=data["artifact_hidden"], inline=False)
    if data.get("extra_note"):       embed.add_field(name="จุดสังเกต", value=data["extra_note"], inline=False)
    embed.set_footer(text="TRETARESIA — Orion City Character Profile")
    await ctx.send(embed=embed)


HELP_CATEGORIES["Orion — TRETARESIA (Quest System)"] = {
    "emoji": "⚔️", "guild": ORION_GUILD_ID,
    "desc": "ระบบเควสต์ AI ของ TRETARESIA",
    "commands": [
        ("?trเข้าร่วม",    "⚔️ เข้าร่วมภารกิจในเธรดปัจจุบัน"),
        ("?trออก",         "🚪 ออกจากภารกิจในเธรดปัจจุบัน"),
        ("?trเมนู",        "📋 เปิดเมนูตัวละคร TRETARESIA"),
        ("?trดูโปรไฟล์",  "👤 ดูโปรไฟล์ผู้เล่นคนอื่น"),
        ("?orionadmin",    "🔒 [Admin] เปิด Admin Panel ของ TRETARESIA"),
    ],
}


# =============================================================
# ORION WEATHER SYSTEM
# =============================================================

_DEFAULT_ORION_AREAS = {
    "orion_city":    {"name": "ORION CITY",         "subtitle": "เขตการปกครองโอไรอ้อน",  "emoji": "🏙️"},
    "wilderness":    {"name": "WILDERNESS",         "subtitle": "กำแพงสู่นอกอาณาจักร",    "emoji": "🌲"},
    "tandria_beach": {"name": "TANDRIA BEACH",      "subtitle": "เขตชายหาดทันเดรีย",      "emoji": "🏖️"},
    "red_light":     {"name": "RED LIGHT DISTRICT", "subtitle": "ย่านโคมแดง",             "emoji": "🌃"},
    "playful_bunny": {"name": "PLAYFUL BUNNY",      "subtitle": "บันนี่คลับ",              "emoji": "🎰"},
}

_DEFAULT_ORION_WEATHERS = {
    "sunny":       {"name": "แดดจ้า",       "emoji": "☀️",  "desc": "ท้องฟ้าโปร่ง แสงอบอุ่นสาดทั่วเขต"},
    "cloudy":      {"name": "เมฆครึ้ม",     "emoji": "☁️",  "desc": "เมฆหนาทึบเข้าปกคลุม แสงแดดถูกบดบัง"},
    "rainy":       {"name": "ฝนพรำ",        "emoji": "🌦️", "desc": "ฝนบางๆ พรำลงมาเป็นช่วงๆ พื้นชื้นเย็น"},
    "storm":       {"name": "พายุฝน",       "emoji": "⛈️",  "desc": "ลมแรง ฟ้าผ่าฉีกท้องฟ้า ฝนสาดหนัก"},
    "thunder":     {"name": "ฟ้าคำราม",     "emoji": "🌩️", "desc": "ฟ้าผ่ารัวๆ แม้ฝนยังไม่ตก"},
    "snowy":       {"name": "หิมะตก",        "emoji": "🌨️", "desc": "เกล็ดหิมะร่วงโปรยทั่วบริเวณ พื้นเป็นสีขาว"},
    "fog":         {"name": "หมอกหนา",       "emoji": "🌫️", "desc": "หมอกหนาทึบ มองไม่เห็นเกิน 3 เมตร"},
    "windy":       {"name": "ลมแรง",         "emoji": "💨",  "desc": "ลมพัดแรงจนต้นไม้เอน"},
    "hot":         {"name": "ร้อนระอุ",      "emoji": "🔥",  "desc": "อากาศร้อนจัด เหงื่อไหลทั้งวัน"},
    "cold":        {"name": "หนาวจัด",       "emoji": "🥶",  "desc": "อุณหภูมิดิ่ง ลมหายใจกลายเป็นไอ"},
    "clear_night": {"name": "ดาวเต็มฟ้า",    "emoji": "🌌",  "desc": "ท้องฟ้าใส ดาวกระจายเต็ม มองเห็นทางช้างเผือก"},
    "drizzle":     {"name": "ฝนปรอย",        "emoji": "💧",  "desc": "ฝนเม็ดเล็กๆ ตกเบาๆ อย่างเงียบเชียบ"},
}


def load_orion_weather_cfg() -> dict:
    cfg = load_json(ORION_WEATHER_FILE, {})
    changed = False
    if not cfg.get("areas"):
        cfg["areas"] = dict(_DEFAULT_ORION_AREAS); changed = True
    if not cfg.get("weathers"):
        cfg["weathers"] = dict(_DEFAULT_ORION_WEATHERS); changed = True
    cfg.setdefault("current", {})
    cfg.setdefault("display_channel_id", 0)
    cfg.setdefault("last_update", 0)
    cfg.setdefault("last_message_id", 0)
    if changed:
        save_orion_weather_cfg(cfg)
    return cfg


def save_orion_weather_cfg(cfg: dict):
    save_json(ORION_WEATHER_FILE, cfg)


def _randomize_orion_weather() -> dict:
    cfg = load_orion_weather_cfg()
    keys = list(cfg.get("weathers", {}).keys())
    if not keys:
        return cfg
    new_cur = {}
    for area_key in cfg.get("areas", {}).keys():
        new_cur[area_key] = _orion_random.choice(keys)
    cfg["current"]     = new_cur
    cfg["last_update"] = int(time.time())
    save_orion_weather_cfg(cfg)
    return cfg


def _build_orion_weather_embed(cfg: dict = None) -> discord.Embed:
    if cfg is None:
        cfg = load_orion_weather_cfg()
    areas    = cfg.get("areas", {})
    weathers = cfg.get("weathers", {})
    current  = cfg.get("current", {})
    last     = cfg.get("last_update", 0)
    next_at  = (last + ORION_WEATHER_CYCLE) if last else (int(time.time()) + ORION_WEATHER_CYCLE)

    embed = discord.Embed(
        title="🌤️  พยากรณ์อากาศ — Orion",
        description="```\nสภาพอากาศเปลี่ยนทุก 32 ชั่วโมง — สุ่มอัตโนมัติ\n```",
        color=0x3498db,
    )
    if not areas:
        embed.add_field(name="​", value="```\nยังไม่มีพื้นที่ในระบบ\n```", inline=False)
    for area_key, area in areas.items():
        w_key = current.get(area_key, "")
        w     = weathers.get(w_key, {})
        if w:
            value = f"{w.get('emoji','❔')}  **{w.get('name','—')}**\n_{w.get('desc','—')}_"
        else:
            value = "_ยังไม่ได้สุ่ม_"
        embed.add_field(
            name=f"{area.get('emoji','📍')}  {area.get('name','—')}  ·  _{area.get('subtitle','')}_",
            value=value, inline=False,
        )
    embed.add_field(
        name="🕒  เปลี่ยนครั้งถัดไป",
        value=f"<t:{int(next_at)}:R>  ·  <t:{int(next_at)}:f>",
        inline=False,
    )
    if last:
        embed.timestamp = datetime.datetime.fromtimestamp(last)
    embed.set_footer(text="Orion  ·  Weather System  ·  อัปเดตล่าสุด")
    return embed


async def _find_orion_weather_message(channel):
    try:
        async for msg in channel.history(limit=100):
            if msg.author.id != bot.user.id or not msg.embeds:
                continue
            for e in msg.embeds:
                footer_text = (e.footer.text or "") if e.footer else ""
                if "Orion" in footer_text and "Weather" in footer_text:
                    return msg
                if e.title and "พยากรณ์อากาศ — Orion" in (e.title or ""):
                    return msg
    except Exception:
        pass
    return None


async def _post_orion_weather_update(force_new: bool = False, edit_only: bool = False):
    cfg   = load_orion_weather_cfg()
    ch_id = cfg.get("display_channel_id", 0)
    if not ch_id:
        return
    guild = bot.get_guild(ORION_GUILD_ID)
    if not guild:
        return
    channel = guild.get_channel(int(ch_id))
    if not channel:
        return
    embed = _build_orion_weather_embed(cfg)
    last_msg_id = cfg.get("last_message_id", 0)

    if not force_new:
        if last_msg_id:
            try:
                msg = await channel.fetch_message(int(last_msg_id))
                await msg.edit(embed=embed)
                return
            except Exception:
                pass
        msg = await _find_orion_weather_message(channel)
        if msg:
            try:
                await msg.edit(embed=embed)
                cfg["last_message_id"] = msg.id
                save_orion_weather_cfg(cfg)
                return
            except Exception:
                pass
        if edit_only:
            return

    try:
        msg = await channel.send(embed=embed)
        cfg["last_message_id"] = msg.id
        save_orion_weather_cfg(cfg)
    except Exception:
        pass


@tasks.loop(minutes=5)
async def orion_weather_task():
    cfg = load_orion_weather_cfg()
    if not cfg.get("display_channel_id"):
        return
    last = cfg.get("last_update", 0)
    if not last:
        return
    now = int(time.time())
    if (now - last) < ORION_WEATHER_CYCLE:
        return
    _randomize_orion_weather()
    await _post_orion_weather_update(edit_only=True)


@orion_weather_task.before_loop
async def _before_orion_weather_task():
    await bot.wait_until_ready()


@bot.command(name="สภาพอากาศ", aliases=["orionweather", "พยากรณ์"])
async def orion_weather_cmd(ctx):
    if not is_orion_guild(ctx):
        return
    cfg = load_orion_weather_cfg()
    if not cfg.get("current"):
        _randomize_orion_weather()
        cfg = load_orion_weather_cfg()
    await ctx.send(embed=_build_orion_weather_embed(cfg))


@bot.tree.command(name="สภาพอากาศ", description="ดูสภาพอากาศปัจจุบันของทุกเขต", guild=_ORION_GUILD_OBJ)
async def orion_weather_slash(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    cfg = load_orion_weather_cfg()
    if not cfg.get("current"):
        _randomize_orion_weather()
        cfg = load_orion_weather_cfg()
    await interaction.response.send_message(embed=_build_orion_weather_embed(cfg), ephemeral=_eph("สภาพอากาศ"))


# ── Weather Admin Modals ──
class OrionSetChannelModal(discord.ui.Modal, title="📍 ตั้งห้องแสดงสภาพอากาศ"):
    ch_input = discord.ui.TextInput(label="Channel ID", placeholder="คลิกขวาห้อง → Copy ID", max_length=25)

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.ch_input.value.strip().lstrip("<#").rstrip(">")
        if not raw.isdigit():
            await interaction.response.send_message("❌ Channel ID ต้องเป็นตัวเลข", ephemeral=True); return
        ch_id = int(raw)
        channel = interaction.guild.get_channel(ch_id)
        if not channel:
            await interaction.response.send_message("❌ ไม่พบห้องนี้", ephemeral=True); return
        cfg = load_orion_weather_cfg()
        cfg["display_channel_id"] = ch_id
        cfg["last_message_id"]    = 0
        save_orion_weather_cfg(cfg)
        if not cfg.get("current"):
            _randomize_orion_weather()
        await _post_orion_weather_update(force_new=True)
        await interaction.response.send_message(f"✅ ตั้งห้องแสดงผลเป็น {channel.mention} แล้ว และโพสต์ embed แล้ว", ephemeral=True)


class OrionAddAreaModal(discord.ui.Modal, title="➕ เพิ่มพื้นที่ใหม่"):
    a_key      = discord.ui.TextInput(label="Key (อังกฤษ ใช้ _ ห้ามเว้นวรรค)", placeholder="เช่น new_zone", max_length=30)
    a_name     = discord.ui.TextInput(label="ชื่อพื้นที่ (ตัวใหญ่)", placeholder="เช่น NEW ZONE", max_length=60)
    a_subtitle = discord.ui.TextInput(label="คำอธิบายสั้น", placeholder="เช่น เขตปลอดภัย", max_length=80)
    a_emoji    = discord.ui.TextInput(label="Emoji", placeholder="เช่น 🌆", max_length=10, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_orion_weather_cfg()
        key = self.a_key.value.strip().lower().replace(" ", "_")
        if not key:
            await interaction.response.send_message("❌ Key ว่าง", ephemeral=True); return
        if key in cfg.get("areas", {}):
            await interaction.response.send_message(f"❌ พื้นที่ key `{key}` มีอยู่แล้ว", ephemeral=True); return
        cfg.setdefault("areas", {})[key] = {
            "name": self.a_name.value.strip(),
            "subtitle": self.a_subtitle.value.strip(),
            "emoji": (self.a_emoji.value or "").strip() or "📍",
        }
        save_orion_weather_cfg(cfg)
        await interaction.response.send_message(f"✅ เพิ่มพื้นที่ `{key}` แล้ว — สุ่มใหม่เพื่อให้มีสภาพอากาศ", ephemeral=True)


class OrionDeleteAreaModal(discord.ui.Modal, title="🗑️ ลบพื้นที่"):
    a_key = discord.ui.TextInput(label="Key พื้นที่ที่จะลบ", placeholder="เช่น orion_city", max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_orion_weather_cfg()
        key = self.a_key.value.strip().lower()
        if key not in cfg.get("areas", {}):
            await interaction.response.send_message(f"❌ ไม่พบพื้นที่ key `{key}`", ephemeral=True); return
        del cfg["areas"][key]
        cfg.get("current", {}).pop(key, None)
        save_orion_weather_cfg(cfg)
        await interaction.response.send_message(f"🗑️ ลบพื้นที่ `{key}` แล้ว", ephemeral=True)


class OrionAddWeatherModal(discord.ui.Modal, title="➕ เพิ่มสภาพอากาศใหม่"):
    w_key   = discord.ui.TextInput(label="Key (อังกฤษ)", placeholder="เช่น hailstorm", max_length=30)
    w_name  = discord.ui.TextInput(label="ชื่อสภาพอากาศ", placeholder="เช่น ลูกเห็บตก", max_length=60)
    w_desc  = discord.ui.TextInput(label="คำบรรยาย", style=discord.TextStyle.paragraph, placeholder="บรรยากาศเป็นอย่างไร...", max_length=200)
    w_emoji = discord.ui.TextInput(label="Emoji", placeholder="เช่น 🧊", max_length=10, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_orion_weather_cfg()
        key = self.w_key.value.strip().lower().replace(" ", "_")
        if not key:
            await interaction.response.send_message("❌ Key ว่าง", ephemeral=True); return
        if key in cfg.get("weathers", {}):
            await interaction.response.send_message(f"❌ Key `{key}` มีอยู่แล้ว", ephemeral=True); return
        cfg.setdefault("weathers", {})[key] = {
            "name": self.w_name.value.strip(),
            "desc": self.w_desc.value.strip(),
            "emoji": (self.w_emoji.value or "").strip() or "❔",
        }
        save_orion_weather_cfg(cfg)
        await interaction.response.send_message(f"✅ เพิ่มสภาพอากาศ `{key}` แล้ว", ephemeral=True)


class OrionDeleteWeatherModal(discord.ui.Modal, title="🗑️ ลบสภาพอากาศ"):
    w_key = discord.ui.TextInput(label="Key สภาพอากาศที่จะลบ", placeholder="เช่น sunny", max_length=30)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_orion_weather_cfg()
        key = self.w_key.value.strip().lower()
        if key not in cfg.get("weathers", {}):
            await interaction.response.send_message(f"❌ ไม่พบ key `{key}`", ephemeral=True); return
        del cfg["weathers"][key]
        for ak, wk in list(cfg.get("current", {}).items()):
            if wk == key:
                cfg["current"][ak] = ""
        save_orion_weather_cfg(cfg)
        await interaction.response.send_message(f"🗑️ ลบสภาพอากาศ `{key}` แล้ว", ephemeral=True)


class OrionWeatherAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ตั้งห้องแสดงผล", style=discord.ButtonStyle.primary, emoji="📍", row=0)
    async def btn_set_channel(self, interaction, button):
        await interaction.response.send_modal(OrionSetChannelModal())

    @discord.ui.button(label="สุ่มใหม่ทันที", style=discord.ButtonStyle.success, emoji="🔄", row=0)
    async def btn_force_random(self, interaction, button):
        _randomize_orion_weather()
        await _post_orion_weather_update(force_new=False)
        await interaction.response.send_message("✅ สุ่มสภาพอากาศใหม่และอัปเดต embed แล้ว", ephemeral=True)

    @discord.ui.button(label="ดูคอนฟิก", style=discord.ButtonStyle.secondary, row=0)
    async def btn_view_cfg(self, interaction, button):
        cfg = load_orion_weather_cfg()
        ch_id = cfg.get("display_channel_id", 0)
        ch_label = f"<#{ch_id}>" if ch_id else "_(ยังไม่ได้ตั้ง)_"
        last = cfg.get("last_update", 0)
        last_label = f"<t:{last}:R>" if last else "_(ยังไม่เคย)_"
        next_at = last + ORION_WEATHER_CYCLE if last else 0
        next_label = f"<t:{next_at}:R>" if next_at else "_(N/A)_"
        areas_text = "\n".join(
            f"• `{k}`  {a.get('emoji','')} **{a.get('name','')}** — _{a.get('subtitle','')}_"
            for k, a in cfg.get("areas", {}).items()
        ) or "_ไม่มี_"
        wx_text = "  ".join(
            f"{w.get('emoji','')}`{k}`"
            for k, w in cfg.get("weathers", {}).items()
        ) or "_ไม่มี_"
        embed = discord.Embed(title="🌤️  Orion Weather — คอนฟิก", color=0x3498db)
        embed.add_field(name="ห้องแสดงผล", value=ch_label, inline=True)
        embed.add_field(name="สุ่มล่าสุด", value=last_label, inline=True)
        embed.add_field(name="ครั้งถัดไป", value=next_label, inline=True)
        embed.add_field(name=f"พื้นที่ ({len(cfg.get('areas', {}))})", value=areas_text[:1000], inline=False)
        embed.add_field(name=f"สภาพอากาศ ({len(cfg.get('weathers', {}))})", value=wx_text[:1000], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="เพิ่มพื้นที่", style=discord.ButtonStyle.success, row=1)
    async def btn_add_area(self, interaction, button):
        await interaction.response.send_modal(OrionAddAreaModal())

    @discord.ui.button(label="ลบพื้นที่", style=discord.ButtonStyle.danger, row=1)
    async def btn_del_area(self, interaction, button):
        await interaction.response.send_modal(OrionDeleteAreaModal())

    @discord.ui.button(label="เพิ่มสภาพอากาศ", style=discord.ButtonStyle.success, row=2)
    async def btn_add_weather(self, interaction, button):
        await interaction.response.send_modal(OrionAddWeatherModal())

    @discord.ui.button(label="ลบสภาพอากาศ", style=discord.ButtonStyle.danger, row=2)
    async def btn_del_weather(self, interaction, button):
        await interaction.response.send_modal(OrionDeleteWeatherModal())


@bot.command(name="สภาพอากาศแอดมิน", aliases=["orionweatheradmin", "weatheradmin"])
@commands.has_permissions(administrator=True)
async def orion_weather_admin_cmd(ctx):
    if not is_orion_guild(ctx):
        return
    cfg      = load_orion_weather_cfg()
    ch_id    = cfg.get("display_channel_id", 0)
    ch_label = f"<#{ch_id}>" if ch_id else "_(ยังไม่ได้ตั้ง)_"
    embed = discord.Embed(
        title="🌤️  Orion Weather — Admin Panel",
        description=(
            "```\nระบบสภาพอากาศ Orion — สุ่มอัตโนมัติทุก 32 ชั่วโมง\n```\n"
            f"**ห้องแสดงผล:** {ch_label}\n"
            f"**พื้นที่:** {len(cfg.get('areas', {}))} เขต  ·  "
            f"**สภาพอากาศ:** {len(cfg.get('weathers', {}))} แบบ\n\n"
            "**Row 0** — 📍 ตั้งห้องแสดง · 🔄 สุ่มใหม่ · 👁️ ดูคอนฟิก\n"
            "**Row 1** — ➕ เพิ่มพื้นที่ · 🗑️ ลบพื้นที่\n"
            "**Row 2** — ➕ เพิ่มสภาพอากาศ · 🗑️ ลบสภาพอากาศ"
        ),
        color=0x3498db,
    )
    await ctx.send(embed=embed, view=OrionWeatherAdminView())


@orion_weather_admin_cmd.error
async def orion_weather_admin_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะ Admin เท่านั้น", delete_after=8)


HELP_CATEGORIES["Orion — Weather System"] = {
    "emoji": "🌤️", "guild": ORION_GUILD_ID,
    "desc": "ระบบสภาพอากาศของเขต Orion — เปลี่ยนทุก 32 ชั่วโมง",
    "commands": [
        ("?สภาพอากาศ",        "🌤️ ดูสภาพอากาศปัจจุบันของทุกเขต"),
        ("?สภาพอากาศแอดมิน", "🔒 [Admin] จัดการพื้นที่/สภาพอากาศ/ห้องแสดง"),
    ],
}


# =============================================================
# ORION CHARACTER PROFILE SYSTEM
# =============================================================

def load_orion_players() -> dict:
    return load_json(ORION_PLAYERS_FILE, {})


def save_orion_players(d: dict):
    save_json(ORION_PLAYERS_FILE, d)


def ensure_orion_player(uid: str):
    data = load_orion_players()
    changed = False
    if uid not in data:
        data[uid] = {
            "char_name": "", "image_url": "", "appearance": "",
            "role": "", "gender": "", "race": "",
            "skills": [], "inventory": [],
            "wallet": 100, "inv": [], "guild_id": "",
            "skill_grants": [{"category_id": "any", "remaining": 1}],
            "registered_at": datetime.datetime.utcnow().strftime("%Y-%m-%d"),
        }
        changed = True
    else:
        for k, v in (("wallet", 100), ("inv", []), ("guild_id", ""), ("skill_grants", []),
                     ("role", ""), ("gender", ""), ("race", "")):
            if k not in data[uid]:
                data[uid][k] = v
                changed = True
    if changed:
        save_orion_players(data)


def total_skill_grants(uid: str) -> int:
    data = load_orion_players()
    return sum(int(g.get("remaining", 0)) for g in data.get(uid, {}).get("skill_grants", []))


def grant_skill_slot(uid: str, category_id: str, qty: int = 1):
    """ให้สิทธิ์สร้างสกิลในหมวด — รวมกับสิทธิ์เดิมในหมวดเดียวกัน"""
    ensure_orion_player(uid)
    data = load_orion_players()
    grants = data[uid].setdefault("skill_grants", [])
    existing = next((g for g in grants if g.get("category_id") == category_id), None)
    if existing:
        existing["remaining"] = int(existing.get("remaining", 0)) + int(qty)
    else:
        grants.append({"category_id": category_id, "remaining": int(qty)})
    save_orion_players(data)


def consume_skill_grant(uid: str, category_id: str) -> bool:
    """หัก 1 สิทธิ์ — ลำดับ: หมวดตรงก่อน, ถ้าไม่มีใช้ 'any' แทน"""
    data = load_orion_players()
    grants = data.get(uid, {}).get("skill_grants", [])
    target = next((g for g in grants if g.get("category_id") == category_id and int(g.get("remaining",0)) > 0), None)
    if not target:
        target = next((g for g in grants if g.get("category_id") == "any" and int(g.get("remaining",0)) > 0), None)
    if not target:
        return False
    target["remaining"] = int(target["remaining"]) - 1
    if target["remaining"] <= 0:
        grants.remove(target)
    save_orion_players(data)
    return True


def _orion_profile_embed(uid: str, author) -> discord.Embed:
    data = load_orion_players()
    p    = data.get(uid, {})
    name = p.get("char_name") or author.display_name
    appearance   = p.get("appearance", "")
    skills_count = len(p.get("skills", []))
    inv_count    = len(p.get("inv", []))
    wallet       = int(p.get("wallet", 0))
    registered   = p.get("registered_at", "—")
    cfg = load_currency_cfg()

    embed = discord.Embed(
        title=name,
        description=(f"_{appearance[:600]}_" if appearance else "_— ยังไม่ได้บรรยายรูปลักษณ์ —_"),
        color=0x6c5ce7,
    )
    embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    img = p.get("image_url", "")
    if img:
        embed.set_image(url=img)
    else:
        embed.set_thumbnail(url=author.display_avatar.url)
    embed.add_field(name=cfg["name"], value=f"`{wallet:,}`", inline=True)
    embed.add_field(name="สกิล",     value=f"`{skills_count}` อัน",   inline=True)
    embed.add_field(name="ไอเทม",    value=f"`{inv_count}` ชนิด",     inline=True)
    role   = p.get("role", "")
    gender = p.get("gender", "")
    race   = p.get("race", "")
    if role or gender or race:
        embed.add_field(name="บทบาท",     value=f"`{role or '—'}`",   inline=True)
        embed.add_field(name="เพศ",       value=f"`{gender or '—'}`", inline=True)
        embed.add_field(name="เผ่าพันธุ์", value=f"`{race or '—'}`",   inline=True)
    embed.set_footer(text=f"ลงทะเบียน {registered}  •  ดูกระเป๋า /ไอเทม")
    return embed


class OrionSetImageModal(discord.ui.Modal, title="🖼️ ตั้งรูปโปรไฟล์"):
    img_input = discord.ui.TextInput(label="URL รูปภาพ", placeholder="วาง URL รูป (เช่น https://...)", max_length=500, required=False)

    def __init__(self, uid: str, author):
        super().__init__()
        self.uid = uid; self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        url = (self.img_input.value or "").strip()
        if url and not url.startswith(("http://", "https://")):
            await interaction.response.send_message("❌ URL ต้องขึ้นด้วย http:// หรือ https://", ephemeral=True); return
        ensure_orion_player(self.uid)
        data = load_orion_players()
        data[self.uid]["image_url"] = url
        save_orion_players(data)
        await interaction.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )


class OrionSetAppearanceModal(discord.ui.Modal, title="✏️ บรรยายรูปลักษณ์"):
    appear_input = discord.ui.TextInput(label="รูปลักษณ์", style=discord.TextStyle.paragraph, placeholder="บรรยายอย่างไรก็ได้ตามที่ต้องการ...", max_length=1000)

    def __init__(self, uid: str, author):
        super().__init__()
        self.uid = uid; self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        ensure_orion_player(self.uid)
        data = load_orion_players()
        data[self.uid]["appearance"] = self.appear_input.value.strip()
        save_orion_players(data)
        await interaction.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )


class OrionSetIdentityModal(discord.ui.Modal, title="ตั้ง บทบาท / เพศ / เผ่าพันธุ์"):
    f_role   = discord.ui.TextInput(label="บทบาท", required=False, max_length=60)
    f_gender = discord.ui.TextInput(label="เพศ", required=False, max_length=30)
    f_race   = discord.ui.TextInput(label="เผ่าพันธุ์", required=False, max_length=60)

    def __init__(self, uid: str, author):
        super().__init__()
        self.uid = uid; self.author = author
        ensure_orion_player(uid)
        p = load_orion_players().get(uid, {})
        self.f_role.default   = p.get("role", "")
        self.f_gender.default = p.get("gender", "")
        self.f_race.default   = p.get("race", "")

    async def on_submit(self, interaction: discord.Interaction):
        data = load_orion_players()
        data[self.uid]["role"]   = self.f_role.value.strip()
        data[self.uid]["gender"] = self.f_gender.value.strip()
        data[self.uid]["race"]   = self.f_race.value.strip()
        save_orion_players(data)
        await interaction.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )


class OrionSetNameModal(discord.ui.Modal, title="📛 ตั้งชื่อตัวละคร"):
    name_input = discord.ui.TextInput(label="ชื่อตัวละคร", max_length=80)

    def __init__(self, uid: str, author):
        super().__init__()
        self.uid = uid; self.author = author

    async def on_submit(self, interaction: discord.Interaction):
        ensure_orion_player(self.uid)
        data = load_orion_players()
        data[self.uid]["char_name"] = self.name_input.value.strip()
        save_orion_players(data)
        await interaction.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )


def _skill_categories(uid: str) -> dict:
    """group skills by origin_type → {category_name: [(idx, skill), ...]}"""
    skills = load_orion_players().get(uid, {}).get("skills", [])
    groups = {}
    for i, sk in enumerate(skills):
        cat = sk.get("origin_type", "ทั่วไป") or "ทั่วไป"
        groups.setdefault(cat, []).append((i, sk))
    return groups


_SKILL_PAGE_SIZE = 5


def _orion_skill_list_embed(uid: str, category: str = None, page: int = 0) -> discord.Embed:
    skills = load_orion_players().get(uid, {}).get("skills", [])
    groups = _skill_categories(uid)
    if category and category in groups:
        sub = groups[category]
        total = len(sub)
        total_pages = max(1, (total + _SKILL_PAGE_SIZE - 1) // _SKILL_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * _SKILL_PAGE_SIZE
        page_sub = sub[start:start + _SKILL_PAGE_SIZE]
        embed = discord.Embed(
            title=f"คลังสกิล — {category}",
            description=(
                f"_เลือกสกิลใน {category} จาก dropdown เพื่อดูรายละเอียด_\n"
                f"_รวม **{total}** อัน — หน้า {page+1}/{total_pages}_"
            ),
            color=0xfdcb6e,
        )
        lines = [f"`{i+1:>2}` {sk.get('emoji','✨')} **{sk.get('name','?')}**" for i, sk in page_sub]
        embed.add_field(name="​", value="\n".join(lines) or "_ว่าง_", inline=False)
    else:
        total = len(skills)
        total_pages = max(1, (total + _SKILL_PAGE_SIZE - 1) // _SKILL_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        embed = discord.Embed(
            title="คลังสกิล",
            description=f"_รวม **{total}** สกิล — เลือกหมวด แล้วเลือกสกิล — หน้า {page+1}/{total_pages}_",
            color=0xfdcb6e,
        )
        if not groups:
            embed.add_field(name="​", value="_ยังไม่มีสกิล — รอแอดมินเพิ่มให้ หรือใช้ `/ฝึกสกิล`_", inline=False)
        else:
            lines = [f"**{cat}** — `{len(lst)}` อัน" for cat, lst in groups.items()]
            embed.add_field(name="หมวดสกิล", value="\n".join(lines), inline=False)
    embed.set_footer(text="Orion · Skill Inventory")
    return embed


class OrionSkillCategorySelect(discord.ui.Select):
    """dropdown เลือกหมวดสกิล"""
    def __init__(self, uid: str, author, current: str = None):
        self.uid = uid; self.author = author
        groups = _skill_categories(uid)
        options = [discord.SelectOption(label="ทุกหมวด", value="__all__",
                                        default=(current is None))]
        for cat, lst in list(groups.items())[:24]:
            options.append(discord.SelectOption(
                label=f"{cat} ({len(lst)})"[:100],
                value=cat,
                description=f"ดูสกิลในหมวด {cat}"[:80],
                default=(cat == current),
            ))
        super().__init__(placeholder="📚 เลือกหมวดสกิล...", options=options, row=0)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        cat = self.values[0]
        cat_filter = None if cat == "__all__" else cat
        await ix.response.edit_message(
            embed=_orion_skill_list_embed(self.uid, cat_filter),
            view=OrionSkillBagView(self.uid, self.author, category=cat_filter),
        )


class OrionSkillSelect(discord.ui.Select):
    def __init__(self, uid: str, author, category: str = None):
        self.uid = uid; self.author = author
        self.category = category
        groups = _skill_categories(uid)
        if category:
            entries = groups.get(category, [])[:25]
        else:
            # flatten ทุกหมวด
            entries = []
            for cat, lst in groups.items():
                entries.extend(lst)
            entries = entries[:25]
        options = []
        for i, sk in entries:
            options.append(discord.SelectOption(
                label=sk.get("name", "?")[:100],
                value=str(i),
                description=(sk.get("context", "")[:80] or sk.get("origin_type","") or "—"),
                emoji=_safe_emoji(sk.get("emoji"), "✨"),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสกิลในหมวดนี้", value="none", emoji="❌")]
        super().__init__(placeholder="✨ เลือกสกิลเพื่อดูรายละเอียด...", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await interaction.response.defer(); return
        idx    = int(self.values[0])
        skills = load_orion_players().get(self.uid, {}).get("skills", [])
        if idx >= len(skills):
            await interaction.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        sk = skills[idx]
        emoji_raw = sk.get("emoji", "")
        icon_url = sk.get("icon_url") or (emoji_raw if isinstance(emoji_raw, str) and emoji_raw.startswith(("http://", "https://")) else "")
        safe = _safe_emoji(emoji_raw, "✨")
        name = (sk.get("name") or "?")[:80]
        title = f"{safe}  {name}"[:250]
        desc = (sk.get("context") or "_ไม่มีคำอธิบาย_")[:4000]
        embed = discord.Embed(title=title, description=desc, color=0xfdcb6e)
        if icon_url:
            embed.set_thumbnail(url=icon_url)
        origin = sk.get("origin_type", "")
        if origin:
            embed.add_field(name="หมวด", value=f"**{origin}**", inline=True)
        if sk.get("rank"):
            embed.add_field(name="Rank", value=sk["rank"], inline=True)
        if sk.get("cooldown_desc"):
            embed.add_field(name="Cooldown", value=sk["cooldown_desc"][:200], inline=True)
        if sk.get("drawback"):
            embed.add_field(name="จุดอ่อน", value=sk["drawback"][:400], inline=False)
        embed.set_footer(text=f"Skill #{idx+1}/{len(skills)}")
        await interaction.response.edit_message(embed=embed, view=OrionSkillBagView(self.uid, self.author, category=self.category))


class OrionSkillBagView(discord.ui.View):
    def __init__(self, uid: str, author, category: str = None, page: int = 0):
        super().__init__(timeout=300)
        self.uid = uid; self.author = author
        self.category = category
        self.page = page
        self.add_item(OrionSkillCategorySelect(uid, author, current=category))
        self.add_item(OrionSkillSelect(uid, author, category=category))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="กลับคลังสกิล", style=discord.ButtonStyle.secondary, row=2)
    async def btn_back_list(self, interaction, button):
        await interaction.response.edit_message(
            embed=_orion_skill_list_embed(self.uid, self.category, self.page),
            view=OrionSkillBagView(self.uid, self.author, category=self.category, page=self.page),
        )

    @discord.ui.button(label="ขอแก้สกิล", style=discord.ButtonStyle.primary, row=2)
    async def btn_request_edit(self, interaction, button):
        skills = load_orion_players().get(self.uid, {}).get("skills", [])
        if not skills:
            await interaction.response.send_message("❌ คุณยังไม่มีสกิล", ephemeral=True); return
        view = discord.ui.View(timeout=180)
        view.add_item(SkillEditRequestSelect(self.uid))
        await interaction.response.send_message(
            "เลือกสกิลที่จะขอแก้ ↓ (ระบบจะส่งคำขอให้แอดมินอนุมัติ)",
            view=view, ephemeral=True,
        )

    @discord.ui.button(label="กลับโปรไฟล์", style=discord.ButtonStyle.primary, emoji="🔙", row=2)
    async def btn_back_profile(self, interaction, button):
        await interaction.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )


class _SkillPageView(discord.ui.View):
    """Pagination view for skill list — shown when player has more than _SKILL_PAGE_SIZE skills in a category"""
    def __init__(self, uid: str, author, category: str = None, page: int = 0):
        super().__init__(timeout=300)
        self.uid = uid; self.author = author
        self.category = category
        self.page = page
        # Calculate total pages
        skills = load_orion_players().get(uid, {}).get("skills", [])
        groups = _skill_categories(uid)
        if category and category in groups:
            total = len(groups[category])
        else:
            total = len(skills)
        self.total_pages = max(1, (total + _SKILL_PAGE_SIZE - 1) // _SKILL_PAGE_SIZE)
        # Add prev/next buttons if needed
        if self.total_pages > 1:
            prev_btn = discord.ui.Button(
                label="◀ ก่อนหน้า",
                style=discord.ButtonStyle.secondary,
                disabled=(page <= 0),
                row=3,
            )
            prev_btn.callback = self._prev
            self.add_item(prev_btn)
            next_btn = discord.ui.Button(
                label="ถัดไป ▶",
                style=discord.ButtonStyle.secondary,
                disabled=(page >= self.total_pages - 1),
                row=3,
            )
            next_btn.callback = self._next
            self.add_item(next_btn)
        # Back to skill bag button
        back_btn = discord.ui.Button(label="กลับคลังสกิล", style=discord.ButtonStyle.primary, row=3)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    async def _prev(self, ix: discord.Interaction):
        new_page = max(0, self.page - 1)
        await ix.response.edit_message(
            embed=_orion_skill_list_embed(self.uid, self.category, new_page),
            view=_SkillPageView(self.uid, self.author, self.category, new_page),
        )

    async def _next(self, ix: discord.Interaction):
        new_page = min(self.total_pages - 1, self.page + 1)
        await ix.response.edit_message(
            embed=_orion_skill_list_embed(self.uid, self.category, new_page),
            view=_SkillPageView(self.uid, self.author, self.category, new_page),
        )

    async def _back(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=_orion_skill_list_embed(self.uid, self.category, self.page),
            view=OrionSkillBagView(self.uid, self.author, category=self.category, page=self.page),
        )


def _orion_item_list_embed(uid: str) -> discord.Embed:
    inv   = load_orion_players().get(uid, {}).get("inventory", [])
    embed = discord.Embed(
        title=f"🎒  กระเป๋า — {len(inv)} ชิ้น",
        description="```\nเลือกไอเทมจาก dropdown เพื่อดูรายละเอียด\n```",
        color=0x55efc4,
    )
    if not inv:
        embed.add_field(name="​", value="_กระเป๋าว่าง — รอแอดมินเพิ่มให้_", inline=False)
    else:
        lines = [f"`{i+1:>2}`  📦 **{it.get('name', '?')}** ×{it.get('qty', 1)}" for i, it in enumerate(inv[:25])]
        embed.add_field(name="📋  รายการ", value="\n".join(lines), inline=False)
    embed.set_footer(text="Orion  ·  Item Bag")
    return embed


class OrionItemSelect(discord.ui.Select):
    def __init__(self, uid: str, author):
        self.uid = uid; self.author = author
        inv = load_orion_players().get(uid, {}).get("inventory", [])[:25]
        options = []
        for i, it in enumerate(inv):
            options.append(discord.SelectOption(
                label=f"{it.get('name', '?')} (×{it.get('qty', 1)})"[:100],
                value=str(i),
                description=(it.get("desc", "")[:80] or "ไม่มีคำอธิบาย"),
            ))
        if not options:
            options = [discord.SelectOption(label="กระเป๋าว่าง", value="none", emoji="❌")]
        super().__init__(placeholder="🎒 เลือกไอเทมเพื่อดูรายละเอียด...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            return
        idx = int(self.values[0])
        inv = load_orion_players().get(self.uid, {}).get("inventory", [])
        if idx >= len(inv):
            await interaction.response.send_message("❌ ไม่พบไอเทม", ephemeral=True); return
        it = inv[idx]
        embed = discord.Embed(
            title=f"📦  {it.get('name', '?')}  ×{it.get('qty', 1)}",
            description=it.get("desc") or "_ไม่มีคำอธิบาย_",
            color=0x55efc4,
        )
        embed.set_footer(text=f"Orion  ·  Item #{idx+1}/{len(inv)}")
        await interaction.response.edit_message(embed=embed, view=OrionItemBagView(self.uid, self.author))


class OrionItemBagView(discord.ui.View):
    def __init__(self, uid: str, author):
        super().__init__(timeout=300)
        self.uid = uid; self.author = author
        self.add_item(OrionItemSelect(uid, author))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="กลับกระเป๋า", style=discord.ButtonStyle.secondary, row=1)
    async def btn_back_list(self, interaction, button):
        await interaction.response.edit_message(
            embed=_orion_item_list_embed(self.uid),
            view=OrionItemBagView(self.uid, self.author),
        )

    @discord.ui.button(label="กลับโปรไฟล์", style=discord.ButtonStyle.primary, emoji="🔙", row=1)
    async def btn_back_profile(self, interaction, button):
        await interaction.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )


# ── Cooldown helper (per-system per-user) ────────────────────
COOLDOWNS_FILE = f"{ORION_DATA_DIR}/cooldowns.json"


def load_cooldowns() -> dict:
    return load_json(COOLDOWNS_FILE, {})


def save_cooldowns(d: dict):
    save_json(COOLDOWNS_FILE, d)


def cooldown_remaining(uid: str, key: str) -> int:
    """คืนวินาทีเหลือ — 0 ถ้าใช้ได้แล้ว"""
    cds = load_cooldowns()
    end_ts = cds.get(uid, {}).get(key, 0)
    now = int(time.time())
    return max(0, int(end_ts) - now)


def set_cooldown(uid: str, key: str, seconds: int):
    cds = load_cooldowns()
    cds.setdefault(uid, {})[key] = int(time.time()) + int(seconds)
    save_cooldowns(cds)


def clear_cooldown(uid: str, key: str):
    cds = load_cooldowns()
    if uid in cds and key in cds[uid]:
        del cds[uid][key]
        save_cooldowns(cds)


def format_cooldown(seconds: int) -> str:
    if seconds <= 0: return "พร้อมใช้งาน"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h: return f"{h}ชม. {m}นาที"
    if m: return f"{m}นาที {s}วิ"
    return f"{s}วิ"


# ── Skill edit requests (player → admin approval) ────────────
SKILL_REQUESTS_FILE = f"{ORION_DATA_DIR}/skill_requests.json"


def load_skill_requests() -> list:
    return load_json(SKILL_REQUESTS_FILE, [])


def save_skill_requests(d: list):
    save_json(SKILL_REQUESTS_FILE, d)


def add_skill_request(uid: str, skill_idx: int, skill_name: str, msg: str) -> str:
    reqs = load_skill_requests()
    rid = _uuid_for_request()
    reqs.append({
        "id":          rid,
        "uid":         uid,
        "skill_idx":   skill_idx,
        "skill_name":  skill_name,
        "message":     msg,
        "status":      "pending",
        "created_at":  int(time.time()),
    })
    save_skill_requests(reqs)
    return rid


def _uuid_for_request() -> str:
    import uuid
    return uuid.uuid4().hex[:8]


class SkillEditRequestSelect(discord.ui.Select):
    def __init__(self, uid: str):
        self.uid = uid
        skills = load_orion_players().get(uid, {}).get("skills", [])[:25]
        options = []
        for i, sk in enumerate(skills):
            options.append(discord.SelectOption(
                label=sk.get("name", "?")[:100],
                value=str(i),
                description=(sk.get("origin_type","") + " — " + sk.get("context","")[:60])[:80],
                emoji=_safe_emoji(sk.get("emoji"), "✨"),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสกิล", value="none")]
        super().__init__(placeholder="เลือกสกิลที่จะขอแก้...", options=options)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await ix.response.defer(); return
        idx = int(self.values[0])
        skills = load_orion_players().get(self.uid, {}).get("skills", [])
        if idx >= len(skills):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        sk = skills[idx]
        await ix.response.send_modal(SkillEditRequestModal(self.uid, idx, sk.get("name","?")))


class SkillEditRequestModal(discord.ui.Modal, title="ขอแก้สกิล"):
    f_msg = discord.ui.TextInput(
        label="ระบุว่าจะแก้อะไร (ส่งให้แอดมินดู)",
        style=discord.TextStyle.paragraph,
        max_length=1500,
        placeholder="เช่น เปลี่ยนชื่อเป็น ... / เพิ่มคำอธิบาย ... / เปลี่ยน icon เป็น ...",
    )

    def __init__(self, uid: str, skill_idx: int, skill_name: str):
        super().__init__()
        self.uid = uid
        self.skill_idx = skill_idx
        self.skill_name = skill_name

    async def on_submit(self, ix: discord.Interaction):
        rid = add_skill_request(self.uid, self.skill_idx, self.skill_name, self.f_msg.value.strip())
        await ix.response.send_message(
            f"✅ ส่งคำขอแก้สกิล **{self.skill_name}** แล้ว (ID: `{rid}`)\n"
            "_แอดมินจะใช้ `/คำขอสกิล` ตรวจสอบและตอบกลับ_",
            ephemeral=True,
        )


# ── Skill categories (admin-managed) ─────────────────────────
SKILL_CATEGORIES_FILE = f"{ORION_DATA_DIR}/skill_categories.json"
CHAR_PENDING_FILE     = f"{ORION_DATA_DIR}/char_pending.json"
CHAR_OPTIONS_FILE     = f"{ORION_DATA_DIR}/char_options.json"
SKILL_PENDING_FILE    = f"{ORION_DATA_DIR}/skill_pending.json"

DEFAULT_SKILL_CATEGORIES = [
    {"id": "false_magic", "name": "False Magic", "emoji": "🔮", "icon_url": "", "description": "เวทมนตร์ลวง",          "transferable": False},
    {"id": "artifact",    "name": "Artifact",    "emoji": "⚙️", "icon_url": "", "description": "พลังจากสิ่งประดิษฐ์", "transferable": True},
    {"id": "aura",        "name": "Aura",        "emoji": "🌟", "icon_url": "", "description": "พลังในตัวเอง",          "transferable": False},
]


def load_skill_cats() -> list:
    cats = load_json(SKILL_CATEGORIES_FILE, None)
    if not cats:
        cats = list(DEFAULT_SKILL_CATEGORIES)
        save_skill_cats(cats)
    return cats


def save_skill_cats(cats: list):
    save_json(SKILL_CATEGORIES_FILE, cats)


def get_skill_cat(cat_id: str):
    return next((c for c in load_skill_cats() if c["id"] == cat_id), None)


# legacy: kept for backwards compat in older code paths
ORIGIN_TYPES = [
    ("false_magic", "False Magic",  "🔮"),
    ("artifact",    "Artifact",     "⚙️"),
    ("aura",        "Aura",         "🌟"),
]


# ── Skill Pending/Review helpers ─────────────────────────────

def _load_skill_pending() -> dict:
    return load_json(SKILL_PENDING_FILE, {})


def _save_skill_pending(d: dict):
    save_json(SKILL_PENDING_FILE, d)


def _skill_review_embed(pid: str, d: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚔️ Skill Review — {d.get('skill_name', '?')}",
        color=0xe67e22,
    )
    embed.set_author(name=f"{d.get('username', '?')} (ID: {d.get('uid', '?')})")
    embed.add_field(name="Skill Name", value=d.get("skill_name", "—"), inline=False)
    embed.add_field(name="Category", value=d.get("category_name", "—"), inline=True)
    embed.add_field(name="Rank", value=d.get("rank", "—"), inline=True)
    embed.add_field(name="Description", value=(d.get("description", "—") or "—")[:500], inline=False)
    if d.get("cooldown_desc"):
        embed.add_field(name="Cooldown", value=d["cooldown_desc"][:200], inline=False)
    if d.get("drawback"):
        embed.add_field(name="Drawback", value=d["drawback"][:400], inline=False)
    embed.set_footer(text=f"ID: {pid} · {d.get('submitted_at', '?')}")
    return embed


async def _post_skill_review(guild, pid: str, d: dict):
    """Post skill review to the configured review channel (forum or regular)."""
    cfg = load_json(f"{ORION_DATA_DIR}/creation_config.json", {})
    ch_id = cfg.get("review_channel_id") or cfg.get("char_review_channel_id")
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch is None:
        return
    embed = _skill_review_embed(pid, d)
    view = _SkillReviewView(pid, d["uid"])
    if isinstance(ch, discord.ForumChannel):
        thread_name = f"[Skill] {d.get('skill_name', '?')} — {d.get('username', '?')}"[:100]
        thread, msg = await ch.create_thread(name=thread_name, embed=embed, view=view)
        pending = _load_skill_pending()
        if pid in pending:
            pending[pid]["review_message_id"] = msg.id
            pending[pid]["review_thread_id"] = thread.id
            _save_skill_pending(pending)
    else:
        msg = await ch.send(embed=embed, view=view)
        pending = _load_skill_pending()
        if pid in pending:
            pending[pid]["review_message_id"] = msg.id
            _save_skill_pending(pending)


class _SkillReviewView(discord.ui.View):
    def __init__(self, pid: str, applicant_uid: str):
        super().__init__(timeout=None)
        self.pid = pid
        self.applicant_uid = applicant_uid

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, row=0)
    async def btn_approve(self, ix: discord.Interaction, _b):
        pending = _load_skill_pending()
        d = pending.get(self.pid)
        if not d:
            await ix.response.send_message("❌ ไม่พบใบสมัครนี้แล้ว", ephemeral=True); return
        uid = d["uid"]
        ensure_orion_player(uid)
        players = load_orion_players()
        cat = get_skill_cat(d.get("category_id", ""))
        s = d.get("icon_url", "")
        if s.lower().startswith(("http://", "https://")):
            emoji = cat.get("emoji", "✨") if cat else "✨"
            icon_url = s
        elif s:
            emoji = s
            icon_url = ""
        else:
            emoji = cat.get("emoji", "✨") if cat else "✨"
            icon_url = cat.get("icon_url", "") if cat else ""
        players[uid].setdefault("skills", []).append({
            "name":         d.get("skill_name", "?"),
            "context":      d.get("description", ""),
            "emoji":        emoji,
            "icon_url":     icon_url,
            "origin_type":  d.get("category_name", "?"),
            "cooldown_desc": d.get("cooldown_desc", ""),
            "drawback":     d.get("drawback", ""),
            "rank":         d.get("rank", "E"),
        })
        save_orion_players(players)
        pending[self.pid]["status"] = "approved"
        _save_skill_pending(pending)
        embed = _skill_review_embed(self.pid, d)
        embed.color = discord.Color.green()
        embed.set_footer(text=f"✅ Approved by {ix.user.display_name}")
        await ix.response.edit_message(embed=embed, view=None)
        # Lock/archive thread if posted in forum
        try:
            if isinstance(ix.channel, discord.Thread):
                await ix.channel.edit(archived=True, locked=True)
        except Exception:
            pass
        try:
            user = await bot.fetch_user(int(uid))
            await user.send(embed=discord.Embed(
                title="✅ สกิลของคุณได้รับการอนุมัติแล้ว!",
                description=f"สกิล **{d.get('skill_name', '?')}** ถูกเพิ่มเข้าในโปรไฟล์ของคุณแล้ว",
                color=discord.Color.green(),
            ))
        except Exception:
            pass

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger, row=0)
    async def btn_decline(self, ix: discord.Interaction, _b):
        pending = _load_skill_pending()
        if self.pid not in pending:
            await ix.response.send_message("❌ ไม่พบใบสมัครนี้แล้ว", ephemeral=True); return
        await ix.response.send_modal(_SkillDeclineModal(self.pid, self.applicant_uid))

    @discord.ui.button(label="✏️ Edit Reason", style=discord.ButtonStyle.primary, row=0)
    async def btn_edit(self, ix: discord.Interaction, _b):
        pending = _load_skill_pending()
        if self.pid not in pending:
            await ix.response.send_message("❌ ไม่พบใบสมัคร", ephemeral=True); return
        await ix.response.send_modal(_SkillEditReasonModal(self.pid, self.applicant_uid))


class _SkillDeclineModal(discord.ui.Modal, title="Decline Reason"):
    f_reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, pid: str, uid: str):
        super().__init__()
        self.pid = pid
        self.uid = uid

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_skill_pending()
        if self.pid in pending:
            pending[self.pid]["status"] = "declined"
            _save_skill_pending(pending)
        d = pending.get(self.pid, {})
        embed = _skill_review_embed(self.pid, d)
        embed.color = discord.Color.red()
        embed.set_footer(text=f"❌ Declined by {ix.user.display_name}")
        await ix.response.edit_message(embed=embed, view=None)
        try:
            user = await bot.fetch_user(int(self.uid))
            await user.send(embed=discord.Embed(
                title="❌ ใบสมัครสกิลถูกปฏิเสธ",
                description=f"**เหตุผล:** {self.f_reason.value.strip()}\nคุณสามารถแก้ไขและสมัครใหม่ได้",
                color=discord.Color.red(),
            ))
        except Exception:
            pass


class _SkillEditReasonModal(discord.ui.Modal, title="Edit Reason (Player must revise)"):
    f_reason = discord.ui.TextInput(label="What to change", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, pid: str, uid: str):
        super().__init__()
        self.pid = pid
        self.uid = uid

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_skill_pending()
        if self.pid in pending:
            pending[self.pid]["status"] = "needs_revision"
            pending[self.pid]["revision_reason"] = self.f_reason.value.strip()
            _save_skill_pending(pending)
        d = pending.get(self.pid, {})
        embed = _skill_review_embed(self.pid, d)
        embed.color = discord.Color.orange()
        embed.add_field(name="Revision Required", value=self.f_reason.value.strip(), inline=False)
        embed.set_footer(text=f"✏️ Needs revision — {ix.user.display_name}")
        await ix.response.edit_message(embed=embed, view=None)
        try:
            user = await bot.fetch_user(int(self.uid))
            await user.send(embed=discord.Embed(
                title="✏️ สกิลของคุณต้องแก้ไข",
                description=(
                    f"**สิ่งที่ต้องแก้ไข:** {self.f_reason.value.strip()}\n"
                    "กรุณาส่งสกิลใหม่ด้วย `/orion` → Create Skill"
                ),
                color=discord.Color.orange(),
            ))
        except Exception:
            pass


# ── CreateSkillModal (pending flow) ──────────────────────────

class CreateSkillModal(discord.ui.Modal, title="สร้างสกิลใหม่"):
    f_name     = discord.ui.TextInput(label="ชื่อสกิล", max_length=80)
    f_icon     = discord.ui.TextInput(label="Icon (emoji หรือ URL รูป)", required=False, max_length=400)
    f_desc     = discord.ui.TextInput(label="คำอธิบายสกิล", style=discord.TextStyle.paragraph, max_length=1500)
    f_rank     = discord.ui.TextInput(label="Rank (เช่น E, D, C, B, A, S — ไม่บังคับ)", required=False, max_length=10)
    f_drawback = discord.ui.TextInput(label="จุดอ่อน / Drawback (ไม่บังคับ)", style=discord.TextStyle.paragraph, required=False, max_length=400)

    def __init__(self, uid: str, author, category: dict):
        super().__init__()
        self.uid = uid
        self.author = author
        self.category = category

    async def on_submit(self, ix: discord.Interaction):
        import uuid as _uuid
        import datetime as _dt
        cat = self.category
        if not consume_skill_grant(self.uid, cat["id"]):
            await ix.response.send_message("❌ ไม่มีสิทธิ์สร้างสกิลในหมวดนี้แล้ว", ephemeral=True); return
        s = (self.f_icon.value or "").strip()
        pid = str(_uuid.uuid4())[:8]
        pending_data = {
            "uid":           self.uid,
            "username":      ix.user.display_name,
            "skill_name":    self.f_name.value.strip(),
            "category_id":   cat["id"],
            "category_name": cat["name"],
            "description":   self.f_desc.value.strip(),
            "rank":          (self.f_rank.value or "").strip() or "E",
            "drawback":      (self.f_drawback.value or "").strip(),
            "cooldown_desc": "",
            "icon_url":      s,
            "status":        "pending",
            "submitted_at":  _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        }
        pending = _load_skill_pending()
        pending[pid] = pending_data
        _save_skill_pending(pending)
        await ix.response.send_message(
            embed=discord.Embed(
                title="📬 ส่งใบสมัครสกิลแล้ว!",
                description=(
                    f"สกิล **{pending_data['skill_name']}** ถูกส่งให้แอดมินตรวจสอบแล้ว\n"
                    "รอการอนุมัติ — คุณจะได้รับ DM เมื่อดำเนินการแล้ว"
                ),
                color=discord.Color.blurple(),
            ),
            ephemeral=True,
        )
        if ix.guild:
            await _post_skill_review(ix.guild, pid, pending_data)


class CreateSkillCategorySelect(discord.ui.Select):
    """dropdown เลือกหมวด — แสดงเฉพาะหมวดที่ผู้เล่นมีสิทธิ์"""
    def __init__(self, uid: str, author):
        self.uid = uid
        self.author = author
        data = load_orion_players()
        grants = data.get(uid, {}).get("skill_grants", [])
        # หาว่าผู้เล่นมีสิทธิ์ในหมวดไหนบ้าง
        has_any = any(g.get("category_id") == "any" and int(g.get("remaining",0)) > 0 for g in grants)
        granted_ids = {g["category_id"] for g in grants if int(g.get("remaining",0)) > 0}
        cats = load_skill_cats()
        options = []
        for c in cats:
            qty = 0
            if has_any:
                qty = sum(int(g.get("remaining",0)) for g in grants if g.get("category_id") in ("any", c["id"]))
            else:
                qty = sum(int(g.get("remaining",0)) for g in grants if g.get("category_id") == c["id"])
            if qty <= 0:
                continue
            options.append(discord.SelectOption(
                label=c.get("name","?")[:100],
                value=c["id"],
                description=f"สิทธิ์เหลือ {qty} ครั้ง · {c.get('description','')[:60]}"[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสิทธิ์สร้างสกิล", value="none")]
        super().__init__(placeholder="เลือกหมวดที่จะสร้างสกิล...", options=options)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await ix.response.defer(); return
        cat = get_skill_cat(self.values[0])
        if not cat:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        await ix.response.send_modal(CreateSkillModal(self.uid, self.author, cat))


class CreateSkillView(discord.ui.View):
    def __init__(self, uid: str, author):
        super().__init__(timeout=300)
        self.add_item(CreateSkillCategorySelect(uid, author))


class OrionProfileView(discord.ui.View):
    """Main player hub — ReQuest-style: ปุ่มเดียวต่อ section + Done"""
    def __init__(self, uid: str, author):
        super().__init__(timeout=None)
        self.uid = uid; self.author = author
        self.add_item(DoneBtn(row=0))
        if total_skill_grants(uid) > 0:
            self.add_item(CreateSkillBtn(uid, author))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="Skills", style=discord.ButtonStyle.primary, row=1)
    async def btn_skills(self, interaction, button):
        await interaction.response.edit_message(
            embed=_orion_skill_list_embed(self.uid),
            view=OrionSkillBagView(self.uid, self.author),
        )

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.primary, row=1)
    async def btn_stats(self, interaction, button):
        try:
            import orion_stats
            p = load_orion_players().get(self.uid, {})
            char_name = p.get("char_name") or self.author.display_name
            await interaction.response.edit_message(
                embed=orion_stats.stats_embed(self.uid, char_name),
                view=_StatsBackView(self.uid, self.author),
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ ระบบ Stats ยังไม่พร้อม: {e}", ephemeral=True)

    @discord.ui.button(label="Edit Character", style=discord.ButtonStyle.primary, row=2)
    async def btn_edit(self, interaction, button):
        embed = make_menu_embed(
            f"Edit Character — {self.author.display_name}",
            [
                ("ตั้งชื่อตัวละคร", "เปลี่ยนชื่อตัวละครของคุณ"),
                ("ตั้งรูปโปรไฟล์", "วาง URL รูปภาพเป็นรูปตัวละคร"),
                ("รูปลักษณ์", "บรรยายรูปลักษณ์ภายนอกของตัวละคร"),
                ("บทบาท / เพศ / เผ่าพันธุ์", "ระบุข้อมูลพื้นฐานของตัวละคร"),
            ],
            color=0x6c5ce7,
        )
        await interaction.response.edit_message(embed=embed, view=OrionEditView(self.uid, self.author))

    @discord.ui.button(label="🗑️ ลบตัวละคร", style=discord.ButtonStyle.danger, row=3)
    async def btn_delete(self, interaction, button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="⚠️ ยืนยันการลบตัวละคร",
                description=(
                    "การลบตัวละครจะ**ลบข้อมูลทั้งหมด**รวมถึง:\n"
                    "• ข้อมูลตัวละคร, สกิล, ไอเทม\n"
                    "• ออกจาก Guild และ Familia\n"
                    "• ไม่สามารถกู้คืนได้\n\n"
                    "**คุณแน่ใจหรือไม่?**"
                ),
                color=discord.Color.red(),
            ),
            view=_DeleteCharConfirmView(self.uid, self.author),
        )


class _StatsBackView(discord.ui.View):
    """Simple back button shown on stats page"""
    def __init__(self, uid: str, author):
        super().__init__(timeout=None)
        self.uid = uid; self.author = author

    async def interaction_check(self, ix):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="◀ กลับ", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix, _b):
        await ix.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )

    @discord.ui.button(label="⚡ ฝึกสถิติ", style=discord.ButtonStyle.primary, row=0)
    async def btn_train(self, ix, _b):
        try:
            import orion_stats
            await orion_stats._start_training(ix, self.uid)
        except Exception as e:
            await ix.response.send_message(f"❌ {e}", ephemeral=True)


class _DeleteCharConfirmView(discord.ui.View):
    def __init__(self, uid: str, author):
        super().__init__(timeout=60)
        self.uid = uid; self.author = author

    async def interaction_check(self, ix):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="✅ ยืนยัน ลบตัวละคร", style=discord.ButtonStyle.danger, row=0)
    async def btn_confirm(self, ix, _b):
        p = load_orion_players().get(self.uid, {})
        char_name = p.get("char_name") or ix.user.display_name
        _delete_player_data(self.uid)
        await ix.response.edit_message(
            embed=discord.Embed(
                description="🗑️ ลบตัวละครเรียบร้อยแล้ว ใช้ `/orion` เพื่อสร้างใหม่",
                color=discord.Color.orange(),
            ),
            view=None,
        )
        try:
            await orion_logs.log_action(self.uid, "char_delete", char_name=char_name)
        except Exception:
            pass

    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cancel(self, ix, _b):
        await ix.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )


# ── Forum-based Character Creation ──────────────────────────

def _load_char_pending() -> dict:
    return load_json(CHAR_PENDING_FILE, {})


def _save_char_pending(d: dict):
    save_json(CHAR_PENDING_FILE, d)


_DEFAULT_CHAR_OPTIONS = {
    "genders":          [],   # [{"label": "ชาย", "role_id": null}, ...]
    "races":            [],   # [{"label": "มนุษย์", "role_id": "12345"}, ...]
    "occupations":      [],   # [{"label": "นักรบ", "role_id": "67890"}, ...]
    "approved_role_ids": [],  # role IDs given to every approved player
}


def _load_char_options() -> dict:
    opts = load_json(CHAR_OPTIONS_FILE, None)
    if opts is None:
        opts = dict(_DEFAULT_CHAR_OPTIONS)
        save_json(CHAR_OPTIONS_FILE, opts)
    for k, v in _DEFAULT_CHAR_OPTIONS.items():
        opts.setdefault(k, v)
    return opts


def _save_char_options(d: dict):
    save_json(CHAR_OPTIONS_FILE, d)


def _char_review_embed(pid: str, d: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"📋 ใบสมัครตัวละคร — {d.get('char_name','?')}",
        color=0xf39c12,
    )
    embed.set_author(name=f"{d.get('username','?')}  (ID: {d.get('uid','?')})")
    if d.get("image_url"):
        embed.set_thumbnail(url=d["image_url"])
    fields = [
        ("ชื่อตัวละคร", d.get("char_name", "—")),
        ("เผ่าพันธุ์", d.get("race", "—")),
        ("เพศ", d.get("gender", "—")),
        ("ชั้น/อาชีพ", d.get("role", "—")),
        ("อายุ", d.get("age", "—")),
        ("รูปลักษณ์", d.get("appearance", "—")[:500]),
        ("ภาพ URL", d.get("image_url", "—")[:200]),
        ("ภูมิหลัง", d.get("background", "—")[:500]),
        ("บุคลิกภาพ", d.get("personality", "—")[:500]),
        ("แรงจูงใจ", d.get("goal", "—")[:500]),
        ("จุดเด่น", d.get("strengths", "—")[:400]),
        ("จุดด้อย", d.get("weaknesses", "—")[:400]),
    ]
    for name, val in fields:
        embed.add_field(name=name, value=val or "—", inline=False)
    embed.set_footer(text=f"ID: {pid} · {d.get('submitted_at', '?')}")
    return embed


async def _post_char_review(guild, pid: str, d: dict):
    cfg = load_json(f"{ORION_DATA_DIR}/creation_config.json", {})
    ch_id = cfg.get("review_channel_id") or cfg.get("char_review_channel_id")
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if ch is None:
        return
    embed = _char_review_embed(pid, d)
    view = _CharReviewView(pid, d["uid"])
    if isinstance(ch, discord.ForumChannel):
        # Post as a forum thread
        char_name = d.get("char_name", "?")
        username = d.get("username", "?")
        thread, msg = await ch.create_thread(
            name=f"[Review] {char_name} — {username}"[:100],
            embed=embed,
            view=view,
        )
        pending = _load_char_pending()
        if pid in pending:
            pending[pid]["review_message_id"] = msg.id
            pending[pid]["review_thread_id"] = thread.id
            _save_char_pending(pending)
    else:
        msg = await ch.send(embed=embed, view=view)
        pending = _load_char_pending()
        if pid in pending:
            pending[pid]["review_message_id"] = msg.id
            _save_char_pending(pending)


class _CharReviewView(discord.ui.View):
    def __init__(self, pid: str, applicant_uid: str):
        super().__init__(timeout=None)
        self.pid = pid
        self.applicant_uid = applicant_uid

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="✅ อนุมัติ", style=discord.ButtonStyle.success, row=0)
    async def btn_approve(self, ix: discord.Interaction, _b):
        pending = _load_char_pending()
        d = pending.get(self.pid)
        if not d:
            await ix.response.send_message("❌ ไม่พบใบสมัครนี้แล้ว (อาจถูกดำเนินการแล้ว)", ephemeral=True); return
        uid = d["uid"]
        ensure_orion_player(uid)
        data = load_orion_players()
        data[uid].update({
            "char_name":   d.get("char_name", ""),
            "race":        d.get("race", ""),
            "gender":      d.get("gender", ""),
            "role":        d.get("role", ""),
            "appearance":  d.get("appearance", ""),
            "image_url":   d.get("image_url", ""),
        })
        data[uid]["background"]   = d.get("background", "")
        data[uid]["personality"]  = d.get("personality", "")
        data[uid]["goal"]         = d.get("goal", "")
        data[uid]["strengths"]    = d.get("strengths", "")
        data[uid]["weaknesses"]   = d.get("weaknesses", "")
        save_orion_players(data)
        # assign roles on approval
        if ix.guild:
            member = ix.guild.get_member(int(uid))
            if member:
                roles_to_add = []
                # 1. approved_role_ids from char_options (base "ผ่านฟอร์ม" roles)
                char_opts = _load_char_options()
                for rid in char_opts.get("approved_role_ids", []):
                    r = ix.guild.get_role(int(rid))
                    if r: roles_to_add.append(r)
                # 2. race-specific role
                race_rid = d.get("race_role_id")
                if race_rid:
                    r = ix.guild.get_role(int(race_rid))
                    if r: roles_to_add.append(r)
                # 3. occupation-specific role
                occ_rid = d.get("occ_role_id")
                if occ_rid:
                    r = ix.guild.get_role(int(occ_rid))
                    if r: roles_to_add.append(r)
                # 4. legacy auto_assign_role from creation_config (backward compat)
                cc_cfg = load_json(f"{ORION_DATA_DIR}/creation_config.json", {})
                legacy_rid = cc_cfg.get("auto_assign_role_id")
                if legacy_rid:
                    r = ix.guild.get_role(int(legacy_rid))
                    if r and r not in roles_to_add: roles_to_add.append(r)
                if roles_to_add:
                    try: await member.add_roles(*roles_to_add)
                    except Exception: pass
        # mark pending as done
        pending[self.pid]["status"] = "approved"
        _save_char_pending(pending)
        embed = _char_review_embed(self.pid, d)
        embed.color = discord.Color.green()
        embed.set_footer(text=f"✅ อนุมัติ by {ix.user.display_name}")
        await ix.response.edit_message(embed=embed, view=None)
        # Lock and archive thread if in a forum
        try:
            if isinstance(ix.channel, discord.Thread):
                await ix.channel.edit(archived=True, locked=True)
        except Exception:
            pass
        # DM applicant
        try:
            user = await bot.fetch_user(int(uid))
            await user.send(
                embed=discord.Embed(
                    title="✅ ตัวละครของคุณได้รับการอนุมัติแล้ว!",
                    description=f"ยินดีด้วย **{d.get('char_name','?')}** ถูกสร้างแล้ว ใช้ `/orion` เพื่อดูโปรไฟล์",
                    color=discord.Color.green(),
                )
            )
        except Exception:
            pass
        # log
        try:
            await orion_logs.log_action(uid, "char_approved", char_name=d.get("char_name","?"))
        except Exception:
            pass

    @discord.ui.button(label="❌ ปฏิเสธ", style=discord.ButtonStyle.danger, row=0)
    async def btn_decline(self, ix: discord.Interaction, _b):
        pending = _load_char_pending()
        if self.pid not in pending:
            await ix.response.send_message("❌ ไม่พบใบสมัครนี้แล้ว", ephemeral=True); return
        await ix.response.send_modal(_CharDeclineModal(self.pid, self.applicant_uid, self.view_embed(pending[self.pid])))

    def view_embed(self, d):
        return _char_review_embed(self.pid, d)

    @discord.ui.button(label="✏️ แก้ไข", style=discord.ButtonStyle.primary, row=0)
    async def btn_edit(self, ix: discord.Interaction, _b):
        pending = _load_char_pending()
        d = pending.get(self.pid, {})
        await ix.response.send_modal(_CharAdminEditModal(self.pid, d))


class _CharDeclineModal(discord.ui.Modal, title="เหตุผลการปฏิเสธ"):
    f_reason = discord.ui.TextInput(label="เหตุผล", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, pid: str, applicant_uid: str, orig_embed):
        super().__init__()
        self.pid = pid
        self.applicant_uid = applicant_uid
        self.orig_embed = orig_embed

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_char_pending()
        if self.pid in pending:
            pending[self.pid]["status"] = "declined"
            _save_char_pending(pending)
        self.orig_embed.color = discord.Color.red()
        self.orig_embed.set_footer(text=f"❌ ปฏิเสธ by {ix.user.display_name}")
        await ix.response.edit_message(embed=self.orig_embed, view=None)
        try:
            user = await bot.fetch_user(int(self.applicant_uid))
            await user.send(
                embed=discord.Embed(
                    title="❌ ใบสมัครตัวละครถูกปฏิเสธ",
                    description=f"**เหตุผล:** {self.f_reason.value.strip()}\n\nคุณสามารถแก้ไขและสมัครใหม่ได้โดยใช้ `/orion`",
                    color=discord.Color.red(),
                )
            )
        except Exception:
            pass
        try:
            await orion_logs.log_action(self.applicant_uid, "char_declined", reason=self.f_reason.value.strip()[:200])
        except Exception:
            pass


class _CharAdminEditModal(discord.ui.Modal, title="แก้ไขใบสมัคร"):
    f_name   = discord.ui.TextInput(label="ชื่อตัวละคร", max_length=50)
    f_race   = discord.ui.TextInput(label="เผ่าพันธุ์", required=False, max_length=50)
    f_role   = discord.ui.TextInput(label="ชั้น/อาชีพ", required=False, max_length=50)
    f_appear = discord.ui.TextInput(label="รูปลักษณ์", style=discord.TextStyle.paragraph, required=False, max_length=500)
    f_bg     = discord.ui.TextInput(label="ภูมิหลัง", style=discord.TextStyle.paragraph, required=False, max_length=500)

    def __init__(self, pid: str, d: dict):
        super().__init__()
        self.pid = pid
        self.f_name.default   = d.get("char_name", "")
        self.f_race.default   = d.get("race", "")
        self.f_role.default   = d.get("role", "")
        self.f_appear.default = d.get("appearance", "")[:500]
        self.f_bg.default     = d.get("background", "")[:500]

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_char_pending()
        if self.pid not in pending:
            await ix.response.send_message("❌ ไม่พบใบสมัครนี้แล้ว", ephemeral=True); return
        d = pending[self.pid]
        if self.f_name.value.strip():   d["char_name"]  = self.f_name.value.strip()
        if self.f_race.value.strip():   d["race"]       = self.f_race.value.strip()
        if self.f_role.value.strip():   d["role"]       = self.f_role.value.strip()
        if self.f_appear.value.strip(): d["appearance"] = self.f_appear.value.strip()
        if self.f_bg.value.strip():     d["background"] = self.f_bg.value.strip()
        _save_char_pending(pending)
        await ix.response.edit_message(embed=_char_review_embed(self.pid, d), view=_CharReviewView(self.pid, d["uid"]))


# ── Character Creation — Dropdown Option Selects ─────────────

async def _submit_char_pending(ix: discord.Interaction, data: dict):
    """Save pending application and post review. Called from final modal or skill-type selection."""
    import uuid as _uuid
    import datetime as _dt
    pid = str(_uuid.uuid4())[:8]
    data["uid"]          = str(ix.user.id)
    data["username"]     = ix.user.display_name
    data["submitted_at"] = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    data["status"]       = "pending"
    pending = _load_char_pending()
    pending[pid] = data
    _save_char_pending(pending)
    submit_embed = discord.Embed(
        title="📬 ส่งใบสมัครแล้ว!",
        description="ใบสมัครตัวละครของคุณถูกส่งให้แอดมินตรวจสอบแล้ว\nรอการอนุมัติ — คุณจะได้รับ DM เมื่อดำเนินการแล้ว",
        color=discord.Color.blurple(),
    )
    if ix.response.is_done():
        # Response already sent (e.g. deferred from skill-type selection)
        await ix.followup.send(embed=submit_embed, ephemeral=True)
    else:
        await ix.response.send_message(embed=submit_embed, ephemeral=True)
    if ix.guild:
        await _post_char_review(ix.guild, pid, data)
    try:
        await orion_logs.log_action(data["uid"], "char_create_submit", char_name=data.get("char_name", "?"))
    except Exception:
        pass


class _CharTextModal2(discord.ui.Modal, title="สร้างตัวละคร — บุคลิกและความสามารถ"):
    f_personality = discord.ui.TextInput(label="บุคลิกภาพ", style=discord.TextStyle.paragraph, max_length=400)
    f_strengths   = discord.ui.TextInput(label="จุดเด่น / ความสามารถ", style=discord.TextStyle.paragraph, max_length=400)
    f_weaknesses  = discord.ui.TextInput(label="จุดด้อย / ข้อจำกัด", style=discord.TextStyle.paragraph, max_length=400)
    f_goal        = discord.ui.TextInput(label="แรงจูงใจ / เป้าหมาย", style=discord.TextStyle.paragraph, max_length=400)

    def __init__(self, prev: dict):
        super().__init__()
        self.prev = prev

    async def on_submit(self, ix: discord.Interaction):
        data = dict(self.prev)
        data["personality"] = self.f_personality.value.strip()
        data["strengths"]   = self.f_strengths.value.strip()
        data["weaknesses"]  = self.f_weaknesses.value.strip()
        data["goal"]        = self.f_goal.value.strip()
        # Show initial skill type selection before submitting
        view = _CharInitialSkillView(data)
        await ix.response.send_message(
            embed=discord.Embed(
                title="⚔️ เลือกประเภทสกิลแรก",
                description=(
                    "กรุณาเลือกประเภทสกิลแรกที่คุณต้องการสร้าง\n"
                    "สกิลนี้จะถูกรวมในใบสมัครตัวละครของคุณ"
                ),
                color=discord.Color.blurple(),
            ),
            view=view,
            ephemeral=True,
        )


class _CharInitialSkillView(discord.ui.View):
    """ให้ผู้เล่นเลือกประเภทสกิลแรกก่อนส่งใบสมัครตัวละคร"""
    def __init__(self, data: dict):
        super().__init__(timeout=300)
        self.data = data
        for skill_type in ["Artifact", "Aura", "False Magic"]:
            btn = discord.ui.Button(label=skill_type, style=discord.ButtonStyle.primary)
            btn.callback = self._make_cb(skill_type)
            self.add_item(btn)

    def _make_cb(self, skill_type: str):
        async def cb(ix: discord.Interaction):
            self.data["initial_skill_type"] = skill_type
            await ix.response.defer()
            for item in self.children:
                item.disabled = True
            await ix.edit_original_response(
                content=f"✅ เลือกประเภทสกิลแรก: **{skill_type}** แล้ว — กำลังส่งใบสมัคร...",
                embed=None,
                view=self,
            )
            await _submit_char_pending(ix, self.data)
        return cb


class _CharTextModal1(discord.ui.Modal, title="สร้างตัวละคร — ข้อมูลพื้นฐาน"):
    f_name       = discord.ui.TextInput(label="ชื่อตัวละคร", max_length=50)
    f_age        = discord.ui.TextInput(label="อายุ", max_length=20)
    f_appearance = discord.ui.TextInput(label="รูปลักษณ์ภายนอก", style=discord.TextStyle.paragraph, max_length=500, placeholder="ผม ดวงตา ส่วนสูง รูปร่าง")
    f_image_url  = discord.ui.TextInput(label="ภาพตัวละคร (URL รูป)", required=False, max_length=400)
    f_background = discord.ui.TextInput(label="ภูมิหลัง / ประวัติ", style=discord.TextStyle.paragraph, max_length=600)

    def __init__(self, prev: dict):
        super().__init__()
        self.prev = prev

    async def on_submit(self, ix: discord.Interaction):
        data = dict(self.prev)
        data["char_name"]  = self.f_name.value.strip()
        data["age"]        = self.f_age.value.strip()
        data["appearance"] = self.f_appearance.value.strip()
        data["image_url"]  = (self.f_image_url.value or "").strip()
        data["background"] = self.f_background.value.strip()
        await ix.response.send_modal(_CharTextModal2(data))


class _GenderSelect(discord.ui.Select):
    def __init__(self, parent_view, options_list: list):
        self.parent_view = parent_view
        opts = [discord.SelectOption(label=o["label"][:100], value=o["label"]) for o in options_list[:25]]
        super().__init__(placeholder="🔵 เลือกเพศ...", options=opts, row=0)

    async def callback(self, ix: discord.Interaction):
        self.parent_view.selected_gender = self.values[0]
        await ix.response.defer()


class _RaceSelect(discord.ui.Select):
    def __init__(self, parent_view, options_list: list):
        self.parent_view = parent_view
        self._data = {o["label"]: o for o in options_list}
        opts = [discord.SelectOption(label=o["label"][:100], value=o["label"]) for o in options_list[:25]]
        super().__init__(placeholder="🟣 เลือกเผ่าพันธุ์...", options=opts, row=1)

    async def callback(self, ix: discord.Interaction):
        chosen = self.values[0]
        self.parent_view.selected_race = chosen
        self.parent_view.selected_race_role = self._data.get(chosen, {}).get("role_id")
        await ix.response.defer()


class _OccupationSelect(discord.ui.Select):
    def __init__(self, parent_view, options_list: list):
        self.parent_view = parent_view
        self._data = {o["label"]: o for o in options_list}
        opts = [discord.SelectOption(label=o["label"][:100], value=o["label"]) for o in options_list[:25]]
        super().__init__(placeholder="🟠 เลือกชั้น/อาชีพ...", options=opts, row=2)

    async def callback(self, ix: discord.Interaction):
        chosen = self.values[0]
        self.parent_view.selected_occupation = chosen
        self.parent_view.selected_occ_role = self._data.get(chosen, {}).get("role_id")
        await ix.response.defer()


class _CharOptionNextBtn(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="ถัดไป →", style=discord.ButtonStyle.success, row=3)
        self.parent_view = parent_view

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.parent_view.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return
        v = self.parent_view
        missing = []
        if v.needs_gender and not v.selected_gender:       missing.append("เพศ")
        if v.needs_race and not v.selected_race:           missing.append("เผ่าพันธุ์")
        if v.needs_occupation and not v.selected_occupation: missing.append("ชั้น/อาชีพ")
        if missing:
            await ix.response.send_message(f"❌ กรุณาเลือกให้ครบ: {', '.join(missing)}", ephemeral=True); return
        data = {
            "gender":         v.selected_gender or "",
            "race":           v.selected_race or "",
            "race_role_id":   v.selected_race_role,
            "occupation":     v.selected_occupation or "",
            "occ_role_id":    v.selected_occ_role,
        }
        await ix.response.send_modal(_CharTextModal1(data))


class _CharOptionSelectView(discord.ui.View):
    def __init__(self, uid: str, author):
        super().__init__(timeout=300)
        self.uid = uid
        self.author = author
        self.selected_gender = None
        self.selected_race = None
        self.selected_race_role = None
        self.selected_occupation = None
        self.selected_occ_role = None

        opts = _load_char_options()
        genders     = opts.get("genders", [])
        races       = opts.get("races", [])
        occupations = opts.get("occupations", [])

        self.needs_gender     = bool(genders)
        self.needs_race       = bool(races)
        self.needs_occupation = bool(occupations)

        if not genders:     self.selected_gender = "—"
        if not races:       self.selected_race = "—"
        if not occupations: self.selected_occupation = "—"

        if genders:     self.add_item(_GenderSelect(self, genders))
        if races:       self.add_item(_RaceSelect(self, races))
        if occupations: self.add_item(_OccupationSelect(self, occupations))
        self.add_item(_CharOptionNextBtn(self))

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True


class _CharCreateStartView(discord.ui.View):
    def __init__(self, uid: str, author):
        super().__init__(timeout=300)
        self.uid = uid
        self.author = author

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="🌟 สร้างตัวละคร", style=discord.ButtonStyle.success, row=0)
    async def btn_create(self, ix: discord.Interaction, _b):
        pending = _load_char_pending()
        uid = str(ix.user.id)
        existing = [p for p in pending.values() if p.get("uid") == uid and p.get("status") == "pending"]
        if existing:
            await ix.response.send_message(
                "⏳ คุณมีใบสมัครที่รออนุมัติอยู่แล้ว กรุณารอแอดมินตรวจสอบ",
                ephemeral=True,
            ); return
        opts = _load_char_options()
        has_dropdowns = any([opts.get("genders"), opts.get("races"), opts.get("occupations")])
        if has_dropdowns:
            embed = discord.Embed(
                title="🌟 สร้างตัวละคร — ขั้นตอนที่ 1",
                description=(
                    "เลือกข้อมูลพื้นฐานของตัวละครจาก dropdown ด้านล่าง\n"
                    "เมื่อเลือกครบทุกรายการแล้วกด **ถัดไป →**"
                ),
                color=discord.Color.blurple(),
            )
            await ix.response.edit_message(embed=embed, view=_CharOptionSelectView(uid, ix.user))
        else:
            await ix.response.send_modal(_CharTextModal1({}))


# ── End Forum-based Character Creation ──────────────────────


class OrionEditView(discord.ui.View):
    """Submenu — แก้ไขข้อมูลตัวละคร (1 button per row, ReQuest style)"""
    def __init__(self, uid: str, author):
        super().__init__(timeout=None)
        self.uid = uid; self.author = author

    async def interaction_check(self, ix):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix, _b):
        await ix.response.edit_message(
            embed=_orion_profile_embed(self.uid, self.author),
            view=OrionProfileView(self.uid, self.author),
        )

    @discord.ui.button(label="ตั้งชื่อตัวละคร", style=discord.ButtonStyle.primary, row=1)
    async def btn_set_name(self, ix, _b):
        await ix.response.send_modal(OrionSetNameModal(self.uid, self.author))

    @discord.ui.button(label="ตั้งรูปโปรไฟล์", style=discord.ButtonStyle.primary, row=2)
    async def btn_set_image(self, ix, _b):
        await ix.response.send_modal(OrionSetImageModal(self.uid, self.author))

    @discord.ui.button(label="รูปลักษณ์", style=discord.ButtonStyle.primary, row=3)
    async def btn_appearance(self, ix, _b):
        await ix.response.send_modal(OrionSetAppearanceModal(self.uid, self.author))

    @discord.ui.button(label="บทบาท / เพศ / เผ่าพันธุ์", style=discord.ButtonStyle.primary, row=4)
    async def btn_identity(self, ix, _b):
        await ix.response.send_modal(OrionSetIdentityModal(self.uid, self.author))


class CreateSkillBtn(discord.ui.Button):
    def __init__(self, uid: str, author):
        n = total_skill_grants(uid)
        super().__init__(label=f"สร้างสกิลใหม่ ({n} สิทธิ์)", style=discord.ButtonStyle.success, row=3)
        self.uid = uid
        self.author = author

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if total_skill_grants(self.uid) <= 0:
            await ix.response.send_message("❌ ไม่มีสิทธิ์สร้างสกิล — ขอแอดมินก่อน", ephemeral=True); return
        cats = load_skill_cats()
        lines = []
        first_icon_url = ""
        for c in cats:
            icon_part = f"[icon]({c['icon_url']}) " if c.get("icon_url") else f"{c.get('emoji','✨')} "
            if c.get("icon_url") and not first_icon_url:
                first_icon_url = c["icon_url"]
            lines.append(f"{icon_part}**{c.get('name','?')}** — _{c.get('description','')[:80]}_")
        embed = discord.Embed(
            title="สร้างสกิลใหม่",
            description=(
                f"_คุณมี **{total_skill_grants(self.uid)}** สิทธิ์ใช้ได้_\n\n" +
                "หมวดที่เปิด:\n" + "\n".join(lines)
            ),
            color=0x6c5ce7,
        )
        if first_icon_url:
            embed.set_thumbnail(url=first_icon_url)
        await ix.response.send_message(
            embed=embed,
            view=CreateSkillView(self.uid, self.author),
            ephemeral=True,
        )


# _ORION_GUILD_OBJ ถูก define ไว้ตอนต้นแล้ว (line 49)


@bot.tree.command(
    name="orion",
    description="ดูโปรไฟล์ตัวละคร Orion (เห็นเฉพาะคุณคนเดียว)",
    guild=_ORION_GUILD_OBJ,
)
async def orion_profile_slash(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    ensure_orion_player(uid)
    p = load_orion_players().get(uid, {})
    # ถ้ายังไม่มีตัวละคร → แสดงหน้าสร้างตัวละคร
    if not p.get("char_name"):
        embed = discord.Embed(
            title="🌟 ยังไม่มีตัวละคร",
            description=(
                "คุณยังไม่มีตัวละครใน Orion Guild\n\n"
                "กดปุ่มด้านล่างเพื่อเริ่มกรอกใบสมัครตัวละคร\n"
                "_(ระบบจะถามข้อมูล 3 ขั้นตอน รวม 12 ฟิลด์ — ต้องการอนุมัติจากแอดมิน)_"
            ),
            color=discord.Color.blurple(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(
            embed=embed,
            view=_CharCreateStartView(uid, interaction.user),
            ephemeral=True,
        )
        return
    await interaction.response.send_message(
        embed=_orion_profile_embed(uid, interaction.user),
        view=OrionProfileView(uid, interaction.user),
        ephemeral=_eph("orion"),
    )


@bot.command(name="orion", aliases=["orionโปรไฟล์", "orionprofile"])
async def orion_profile_cmd(ctx):
    if not is_orion_guild(ctx):
        return
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound, AttributeError):
        pass
    await ctx.send(
        f"{ctx.author.mention} กรุณาใช้ **`/orion`** แทน — เพื่อให้โปรไฟล์เห็นเฉพาะคุณคนเดียว\n"
        "_(ถ้าพิมพ์ `/` แล้วไม่เจอ ให้ลองรีโหลด Discord สักครู่)_",
        delete_after=15,
    )


# ── Admin Modals ──
def _orion_parse_user_id(raw: str) -> str:
    return "".join(c for c in raw if c.isdigit())


class _OrionAddSkillModal(discord.ui.Modal, title="✨ เพิ่มสกิลให้ผู้เล่น"):
    f_name    = discord.ui.TextInput(label="ชื่อสกิล", max_length=80)
    f_icon    = discord.ui.TextInput(label="Icon (emoji / <:server:id> / URL)", required=False, max_length=400)
    f_context = discord.ui.TextInput(label="คำอธิบาย / Context", style=discord.TextStyle.paragraph, max_length=1500)
    f_origin  = discord.ui.TextInput(label="หมวด (เช่น Technique / Magic — ว่าง=ทั่วไป)", required=False, max_length=50)

    def __init__(self, target_uids: list, target_names: list):
        super().__init__()
        self.target_uids = target_uids
        self.target_names = target_names

    async def on_submit(self, ix: discord.Interaction):
        icon = (self.f_icon.value or "").strip()
        if icon.lower().startswith(("http://", "https://")):
            emoji, icon_url = "✨", icon
        else:
            # sanitize emoji input — เก็บเฉพาะที่ Discord ยอมรับ
            emoji = _safe_emoji(icon, "✨") if icon else "✨"
            icon_url = ""
        origin = (self.f_origin.value or "ทั่วไป").strip() or "ทั่วไป"
        skill = {
            "name": self.f_name.value.strip(),
            "context": self.f_context.value.strip(),
            "emoji": emoji,
            "icon_url": icon_url,
            "origin_type": origin,
        }
        data = load_orion_players()
        for uid in self.target_uids:
            ensure_orion_player(uid)
            data = load_orion_players()
            data[uid].setdefault("skills", []).append(dict(skill))
            save_orion_players(data)
        await ix.response.send_message(
            f"✅ เพิ่มสกิล **{skill['name']}** ให้ {len(self.target_uids)} คน: "
            f"{', '.join(self.target_names[:25])}",
            ephemeral=True,
        )


class OrionAddSkillUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="👤 เลือกผู้เล่น (เลือกได้หลายคน)...", min_values=1, max_values=25)

    async def callback(self, ix: discord.Interaction):
        targets = [u for u in self.values if not u.bot]
        if not targets:
            await ix.response.send_message("❌ ไม่มีผู้เล่นที่ใช้ได้", ephemeral=True); return
        uids = [str(u.id) for u in targets]
        names = [u.display_name for u in targets]
        await ix.response.send_modal(_OrionAddSkillModal(uids, names))


class OrionAddSkillView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(OrionAddSkillUserSelect())


# ── แก้สกิล / ลบสกิล: UserSelect → dropdown skills ────────────
class _SkillPickAction(discord.ui.Select):
    def __init__(self, target_uid: str, target_name: str, action: str):
        self.target_uid = target_uid
        self.target_name = target_name
        self.action = action
        skills = load_orion_players().get(target_uid, {}).get("skills", [])
        options = []
        for i, sk in enumerate(skills[:25]):
            options.append(discord.SelectOption(
                label=sk.get("name","?")[:100],
                value=str(i),
                description=(sk.get("context","")[:80] or "—"),
                emoji=_safe_emoji(sk.get("emoji"), "✨"),
            ))
        if not options:
            options = [discord.SelectOption(label="ผู้เล่นนี้ไม่มีสกิล", value="none")]
        super().__init__(placeholder=f"เลือกสกิลของ {target_name}...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        idx = int(self.values[0])
        data = load_orion_players()
        skills = data.get(self.target_uid, {}).get("skills", [])
        if idx >= len(skills):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        if self.action == "delete":
            removed = skills.pop(idx)
            save_orion_players(data)
            await ix.response.edit_message(content=f"🗑️ ลบ **{removed.get('name')}** ของ **{self.target_name}**", view=None)
        elif self.action == "edit":
            await ix.response.send_modal(_SkillEditModal(self.target_uid, self.target_name, idx))


class _SkillEditModal(discord.ui.Modal, title="✏️ แก้สกิล"):
    f_name    = discord.ui.TextInput(label="ชื่อใหม่ (ว่าง=ไม่เปลี่ยน)", required=False, max_length=80)
    f_icon    = discord.ui.TextInput(label="Icon ใหม่ (ว่าง=ไม่เปลี่ยน)", required=False, max_length=400)
    f_context = discord.ui.TextInput(label="Context ใหม่ (ว่าง=ไม่เปลี่ยน)", style=discord.TextStyle.paragraph, required=False, max_length=1500)
    f_origin  = discord.ui.TextInput(label="หมวดใหม่ (ว่าง=ไม่เปลี่ยน)", required=False, max_length=50)

    def __init__(self, target_uid: str, target_name: str, idx: int):
        super().__init__()
        self.target_uid = target_uid
        self.target_name = target_name
        self.idx = idx
        sk = load_orion_players().get(target_uid, {}).get("skills", [])[idx]
        self.f_name.default    = sk.get("name", "")
        self.f_context.default = sk.get("context", "")[:1500]
        self.f_origin.default  = sk.get("origin_type", "")

    async def on_submit(self, ix: discord.Interaction):
        data = load_orion_players()
        sk = data.get(self.target_uid, {}).get("skills", [])[self.idx]
        if self.f_name.value.strip():    sk["name"] = self.f_name.value.strip()
        if self.f_context.value.strip(): sk["context"] = self.f_context.value.strip()
        if self.f_origin.value.strip():  sk["origin_type"] = self.f_origin.value.strip()
        if self.f_icon.value.strip():
            icon = self.f_icon.value.strip()
            if icon.lower().startswith(("http://","https://")):
                sk["emoji"] = "✨"; sk["icon_url"] = icon
            else:
                sk["emoji"] = icon; sk["icon_url"] = ""
        save_orion_players(data)
        await ix.response.send_message(f"✅ อัปเดต **{sk.get('name')}** ของ **{self.target_name}** แล้ว", ephemeral=True)


class _SkillActionUserSelect(discord.ui.UserSelect):
    def __init__(self, action: str):
        super().__init__(placeholder="👤 เลือกผู้เล่น...", min_values=1, max_values=1)
        self.action = action

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ บอทไม่มีสกิล", ephemeral=True); return
        view = discord.ui.View(timeout=180)
        view.add_item(_SkillPickAction(str(target.id), target.display_name, self.action))
        await ix.response.send_message(
            f"เลือกสกิลของ **{target.display_name}** ↓",
            view=view,
            ephemeral=True,
        )


class OrionEditSkillView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(_SkillActionUserSelect("edit"))


class OrionDeleteSkillView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(_SkillActionUserSelect("delete"))


class OrionAddItemModal(discord.ui.Modal, title="🎁 เพิ่มไอเทมให้ผู้เล่น"):
    target    = discord.ui.TextInput(label="User ID หรือ @mention", max_length=80)
    item_name = discord.ui.TextInput(label="ชื่อไอเทม", max_length=80)
    item_qty  = discord.ui.TextInput(label="จำนวน", placeholder="1", max_length=5)
    item_desc = discord.ui.TextInput(label="คำอธิบาย (ไม่บังคับ)", style=discord.TextStyle.paragraph, max_length=500, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        uid = _orion_parse_user_id(self.target.value)
        if not uid:
            await interaction.response.send_message("❌ User ID ไม่ถูกต้อง", ephemeral=True); return
        raw_qty = (self.item_qty.value or "1").strip()
        if not raw_qty.isdigit() or int(raw_qty) < 1:
            await interaction.response.send_message("❌ จำนวนต้องเป็นตัวเลข 1 ขึ้นไป", ephemeral=True); return
        qty = int(raw_qty)
        ensure_orion_player(uid)
        data = load_orion_players()
        inv  = data[uid].setdefault("inventory", [])
        item_name = self.item_name.value.strip()
        existing  = next((it for it in inv if it.get("name") == item_name), None)
        if existing:
            existing["qty"] = existing.get("qty", 1) + qty
            if self.item_desc.value:
                existing["desc"] = self.item_desc.value.strip()
        else:
            inv.append({"name": item_name, "qty": qty, "desc": (self.item_desc.value or "").strip()})
        save_orion_players(data)
        await interaction.response.send_message(f"✅ เพิ่ม **{item_name}** ×{qty} ให้ <@{uid}> แล้ว", ephemeral=True)


class OrionDeleteItemModal(discord.ui.Modal, title="🗑️ ลบไอเทมของผู้เล่น"):
    target    = discord.ui.TextInput(label="User ID หรือ @mention", max_length=80)
    item_name = discord.ui.TextInput(label="ชื่อไอเทมที่จะลบ", max_length=80)
    item_qty  = discord.ui.TextInput(label="จำนวนที่ลบ (ว่าง=ลบทั้งหมด)", placeholder="เช่น 2", max_length=5, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        uid = _orion_parse_user_id(self.target.value)
        if not uid:
            await interaction.response.send_message("❌ User ID ไม่ถูกต้อง", ephemeral=True); return
        data = load_orion_players()
        inv  = data.get(uid, {}).get("inventory", [])
        name = self.item_name.value.strip()
        idx  = next((i for i, it in enumerate(inv) if it.get("name") == name), -1)
        if idx < 0:
            await interaction.response.send_message(f"❌ ไม่พบไอเทม `{name}` ใน <@{uid}>", ephemeral=True); return
        raw_qty = (self.item_qty.value or "").strip()
        if raw_qty:
            if not raw_qty.isdigit() or int(raw_qty) < 1:
                await interaction.response.send_message("❌ จำนวนต้องเป็นตัวเลข", ephemeral=True); return
            qty = int(raw_qty)
            inv[idx]["qty"] = inv[idx].get("qty", 1) - qty
            if inv[idx]["qty"] <= 0:
                inv.pop(idx)
                msg = f"🗑️ ลบ **{name}** ทั้งหมดของ <@{uid}>"
            else:
                msg = f"🗑️ ลบ **{name}** −{qty} ของ <@{uid}> (เหลือ {inv[idx]['qty']})"
        else:
            inv.pop(idx)
            msg = f"🗑️ ลบ **{name}** ทั้งหมดของ <@{uid}>"
        save_orion_players(data)
        await interaction.response.send_message(msg, ephemeral=True)


def _admin_player_summary_embed(uid: str, target) -> discord.Embed:
    p = load_orion_players().get(uid, {})
    if not p:
        return discord.Embed(
            title=f"ข้อมูลผู้เล่น — {target.display_name}",
            description=f"❌ ไม่พบข้อมูล <@{uid}> ในระบบ",
            color=0x95a5a6,
        )
    embed = discord.Embed(
        title=f"ข้อมูลผู้เล่น — {target.display_name}",
        description=(
            f"<@{uid}>\n"
            f"**ชื่อตัวละคร:** `{p.get('char_name','—')}`\n"
            f"**ลงทะเบียน:** `{p.get('registered_at','—')}`"
        ),
        color=0x6c5ce7,
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="เงิน",  value=f"`{int(p.get('wallet',0)):,}`", inline=True)
    embed.add_field(name="สกิล",  value=f"`{len(p.get('skills',[]))}` อัน", inline=True)
    embed.add_field(name="ไอเทม", value=f"`{len(p.get('inv',[]))}` ชนิด", inline=True)
    appearance = p.get("appearance", "")
    if appearance:
        embed.add_field(name="รูปลักษณ์", value=f"_{appearance[:500]}_", inline=False)
    embed.set_footer(text="เลือกสกิลจาก dropdown ด้านล่างเพื่อดูรายละเอียด")
    return embed


def _admin_skill_detail_embed(uid: str, target, sk: dict, idx: int, total: int) -> discord.Embed:
    emoji_raw = sk.get("emoji", "")
    icon_url = sk.get("icon_url") or (emoji_raw if isinstance(emoji_raw, str) and emoji_raw.startswith(("http://", "https://")) else "")
    safe = _safe_emoji(emoji_raw, "✨")
    name = (sk.get("name") or "?")[:80]
    title = f"{safe}  {name}"[:250]
    desc = (sk.get("context") or "_— ไม่มีคำอธิบาย —_")[:4000]
    embed = discord.Embed(title=title, description=desc, color=0xfdcb6e)
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    embed.add_field(name="หมวด", value=f"`{sk.get('origin_type','-')}`", inline=True)
    # โชว์ emoji raw (อาจจะเป็น text) แบบ truncate
    raw_show = (str(sk.get('emoji','-')) or '-')[:50]
    embed.add_field(name="Emoji (เก็บ)", value=f"`{raw_show}`", inline=True)
    icon_show = sk.get("icon_url", "")
    if icon_show:
        embed.add_field(name="Icon URL", value=f"[link]({icon_show[:200]})", inline=True)
    embed.set_author(name=f"{target.display_name}", icon_url=target.display_avatar.url)
    embed.set_footer(text=f"Skill {idx+1}/{total} · User ID: {uid}")
    return embed


class AdminPlayerSkillSelect(discord.ui.Select):
    def __init__(self, uid: str, target):
        self.uid = uid
        self.target = target
        skills = load_orion_players().get(uid, {}).get("skills", [])[:25]
        options = []
        for i, sk in enumerate(skills):
            options.append(discord.SelectOption(
                label=sk.get("name", "?")[:100],
                value=str(i),
                description=f"{sk.get('origin_type','-')} · {(sk.get('context','')[:60] or '—')}"[:80],
                emoji=_safe_emoji(sk.get("emoji"), "✨"),
            ))
        if not options:
            options = [discord.SelectOption(label="ผู้เล่นนี้ไม่มีสกิล", value="none")]
        super().__init__(placeholder="เลือกสกิลเพื่อดูรายละเอียดเต็ม...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        idx = int(self.values[0])
        skills = load_orion_players().get(self.uid, {}).get("skills", [])
        if idx >= len(skills):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        sk = skills[idx]
        await ix.response.edit_message(
            embed=_admin_skill_detail_embed(self.uid, self.target, sk, idx, len(skills)),
            view=AdminPlayerSkillsView(self.uid, self.target),
        )


class AdminPlayerSkillsView(discord.ui.View):
    def __init__(self, uid: str, target):
        super().__init__(timeout=300)
        self.uid = uid
        self.target = target
        self.add_item(AdminPlayerSkillSelect(uid, target))

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="กลับสรุป", style=discord.ButtonStyle.secondary, row=1)
    async def btn_back(self, ix, _b):
        await ix.response.edit_message(
            embed=_admin_player_summary_embed(self.uid, self.target),
            view=AdminPlayerSkillsView(self.uid, self.target),
        )


class OrionViewPlayerUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="เลือกผู้เล่นที่จะดู...", min_values=1, max_values=1)

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        uid = str(target.id)
        await ix.response.send_message(
            embed=_admin_player_summary_embed(uid, target),
            view=AdminPlayerSkillsView(uid, target),
            ephemeral=True,
        )


class OrionViewPlayerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(OrionViewPlayerUserSelect())


# ── Admin: View Player Profile (same as OrionProfileView but admin-accessible) ──

class AdminProfileView(discord.ui.View):
    """Shows a player's full profile from admin perspective — no interaction_check blocking admin"""
    def __init__(self, uid: str, target):
        super().__init__(timeout=300)
        self.uid = uid
        self.target = target

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Skills", style=discord.ButtonStyle.primary, row=0)
    async def btn_skills(self, ix, _b):
        skills = load_orion_players().get(self.uid, {}).get("skills", [])
        embed = _orion_skill_list_embed(self.uid)
        embed.set_footer(text=f"Orion · Skill Inventory (Admin View) · {self.target.display_name}")
        await ix.response.edit_message(
            embed=embed,
            view=AdminSkillBagView(self.uid, self.target),
        )

    @discord.ui.button(label="กลับ", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix, _b):
        embed = _orion_profile_embed(self.uid, self.target)
        embed.set_footer(text=f"(Admin View) · {self.target.display_name}")
        await ix.response.edit_message(embed=embed, view=AdminProfileView(self.uid, self.target))


def _admin_orion_profile_embed(uid: str, target) -> discord.Embed:
    """Like _orion_profile_embed but with (Admin View) footer"""
    embed = _orion_profile_embed(uid, target)
    embed.set_footer(text=f"(Admin View) · {target.display_name} (ID: {uid})")
    return embed


class AdminSkillBagView(discord.ui.View):
    """Admin view of a player's skill bag"""
    def __init__(self, uid: str, target):
        super().__init__(timeout=300)
        self.uid = uid
        self.target = target

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="กลับโปรไฟล์", style=discord.ButtonStyle.primary, row=0)
    async def btn_back(self, ix, _b):
        await ix.response.edit_message(
            embed=_admin_orion_profile_embed(self.uid, self.target),
            view=AdminProfileView(self.uid, self.target),
        )


class AdminViewProfileUserSelect(discord.ui.UserSelect):
    """Lets admin pick a player and view their full OrionProfileView-style profile"""
    def __init__(self):
        super().__init__(placeholder="เลือกผู้เล่นที่จะดูโปรไฟล์...", min_values=1, max_values=1)

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        uid = str(target.id)
        ensure_orion_player(uid)
        embed = _admin_orion_profile_embed(uid, target)
        await ix.response.send_message(
            embed=embed,
            view=AdminProfileView(uid, target),
            ephemeral=True,
        )


class AdminViewProfileView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(AdminViewProfileUserSelect())


# ── Delete Player (ลบข้อมูลผู้เล่นทั้งหมด) ───────────────────
def _delete_player_data(uid: str):
    """ลบข้อมูลผู้เล่นใน orion_players + ออกจาก Familia/Guild + clear pending"""
    # 1) orion_players.json
    data = load_orion_players()
    data.pop(uid, None)
    save_orion_players(data)
    # 2) Guild
    try:
        guilds = load_guilds()
        changed = False
        to_remove = []
        for gid, g in guilds.items():
            before = len(g.get("members", []))
            g["members"] = [m for m in g.get("members", []) if m.get("uid") != uid]
            g["invites"] = [u for u in g.get("invites", []) if u != uid]
            if len(g["members"]) != before:
                changed = True
            # ถ้าเป็น owner → ยุบทั้ง guild
            if g.get("owner_id") == uid:
                to_remove.append(gid)
        for gid in to_remove:
            guilds.pop(gid, None); changed = True
        if changed:
            save_guilds(guilds)
    except Exception as e:
        print(f"[delete_player] guild cleanup: {e}")
    # 3) Familia
    try:
        fams = orion_familia.load_familias()
        changed = False
        to_remove = []
        for fid, f in fams.items():
            before = len(f.get("members", []))
            f["members"] = [m for m in f.get("members", []) if m.get("uid") != uid]
            f["invites"] = [u for u in f.get("invites", []) if u != uid]
            if len(f["members"]) != before:
                changed = True
            if f.get("leader_id") == uid:
                to_remove.append(fid)
        for fid in to_remove:
            fams.pop(fid, None); changed = True
        if changed:
            orion_familia.save_familias(fams)
    except Exception as e:
        print(f"[delete_player] familia cleanup: {e}")


def _player_summary(uid: str, member) -> discord.Embed:
    p = load_orion_players().get(uid, {})
    if not p:
        return discord.Embed(
            title="ลบข้อมูลผู้เล่น",
            description=f"❌ ไม่พบข้อมูล **{member.display_name}** ในระบบ — ไม่มีอะไรให้ลบ",
            color=0x95a5a6,
        )
    skills = len(p.get("skills", []))
    inv = len(p.get("inv", []))
    wallet = int(p.get("wallet", 0))
    char_name = p.get("char_name", "—")
    embed = discord.Embed(
        title=f"⚠️ ยืนยันลบข้อมูล — {member.display_name}",
        description=(
            "**กำลังจะลบข้อมูลต่อไปนี้ — ย้อนกลับไม่ได้!**\n"
            f"• ชื่อตัวละคร: `{char_name}`\n"
            f"• เงิน: `{wallet:,}`\n"
            f"• สกิล: `{skills}` อัน\n"
            f"• ไอเทมในกระเป๋า: `{inv}` ชนิด\n"
            f"• รูปลักษณ์ + รูปโปรไฟล์\n"
            f"• ออกจาก Guild / Familia ที่อยู่ (ถ้าเป็นหัว → ยุบทั้งกลุ่ม)"
        ),
        color=0xe74c3c,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text=f"User ID: {uid}")
    return embed


class DeletePlayerConfirmView(discord.ui.View):
    def __init__(self, uid: str, member):
        super().__init__(timeout=60)
        self.uid = uid
        self.member = member

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ยืนยันลบทั้งหมด", style=discord.ButtonStyle.danger)
    async def btn_yes(self, ix: discord.Interaction, _b):
        _delete_player_data(self.uid)
        await ix.response.edit_message(
            content=f"💥 ลบข้อมูลของ **{self.member.display_name}** เรียบร้อย",
            embed=None, view=None,
        )

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def btn_no(self, ix: discord.Interaction, _b):
        await ix.response.edit_message(content="❌ ยกเลิก", embed=None, view=None)


class OrionDeletePlayerUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="เลือกผู้เล่นที่จะลบข้อมูล...", min_values=1, max_values=1)

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ ไม่ใช่ผู้เล่น", ephemeral=True); return
        uid = str(target.id)
        await ix.response.send_message(
            embed=_player_summary(uid, target),
            view=DeletePlayerConfirmView(uid, target),
            ephemeral=True,
        )


class OrionDeletePlayerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(OrionDeletePlayerUserSelect())


# ── Admin: Skill Category CRUD ───────────────────────────────
class SkillCatAddModal(discord.ui.Modal, title="เพิ่มหมวดสกิล"):
    f_id   = discord.ui.TextInput(label="ID (a-z, _) — เช่น divine_magic", max_length=40)
    f_name = discord.ui.TextInput(label="ชื่อหมวด", max_length=60)
    f_icon = discord.ui.TextInput(
        label="Icon (emoji หรือ URL รูป)",
        placeholder="🔮 หรือ https://i.imgur.com/xxx.png",
        required=False, max_length=400,
    )
    f_desc = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)

    async def on_submit(self, ix: discord.Interaction):
        cid = self.f_id.value.strip().lower().replace(" ", "_")
        if not cid:
            await ix.response.send_message("❌ ID ว่าง", ephemeral=True); return
        cats = load_skill_cats()
        if any(c["id"] == cid for c in cats):
            await ix.response.send_message(f"❌ มี ID `{cid}` อยู่แล้ว", ephemeral=True); return
        icon = (self.f_icon.value or "").strip()
        if icon.lower().startswith(("http://", "https://")):
            emoji, icon_url = "✨", icon
        else:
            emoji, icon_url = (icon or "✨"), ""
        cats.append({
            "id": cid,
            "name": self.f_name.value.strip(),
            "emoji": emoji,
            "icon_url": icon_url,
            "description": (self.f_desc.value or "").strip(),
        })
        save_skill_cats(cats)
        kind = "URL รูป" if icon_url else "emoji"
        await ix.response.send_message(f"✅ เพิ่มหมวด `{cid}` — **{self.f_name.value}** (icon: {kind})", ephemeral=True)


class SkillCatEditSelect(discord.ui.Select):
    def __init__(self):
        cats = load_skill_cats()
        options = []
        for c in cats[:25]:
            options.append(discord.SelectOption(
                label=c.get("name","?")[:100],
                value=c["id"],
                description=(c.get("description","")[:80] or "—"),
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีหมวด", value="none")]
        super().__init__(placeholder="เลือกหมวดที่จะแก้...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        c = get_skill_cat(self.values[0])
        modal = SkillCatEditModal(c["id"])
        modal.f_name.default = c.get("name", "")
        # ใส่ icon_url ก่อน ถ้าไม่มีค่อย emoji
        modal.f_icon.default = c.get("icon_url") or c.get("emoji", "")
        modal.f_desc.default = c.get("description", "")
        await ix.response.send_modal(modal)


class SkillCatEditModal(discord.ui.Modal, title="แก้หมวดสกิล"):
    f_name = discord.ui.TextInput(label="ชื่อหมวด", max_length=60)
    f_icon = discord.ui.TextInput(label="Icon (emoji หรือ URL)", required=False, max_length=400)
    f_desc = discord.ui.TextInput(label="คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)

    def __init__(self, cid: str):
        super().__init__()
        self.cid = cid

    async def on_submit(self, ix: discord.Interaction):
        cats = load_skill_cats()
        c = next((x for x in cats if x["id"] == self.cid), None)
        if not c:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        c["name"] = self.f_name.value.strip() or c["name"]
        icon = (self.f_icon.value or "").strip()
        if icon:
            if icon.lower().startswith(("http://", "https://")):
                c["emoji"] = "✨"
                c["icon_url"] = icon
            else:
                c["emoji"] = icon
                c["icon_url"] = ""
        c["description"] = self.f_desc.value.strip()
        save_skill_cats(cats)
        kind = "URL รูป" if c.get("icon_url") else "emoji"
        await ix.response.send_message(f"✅ อัปเดต `{self.cid}` (icon: {kind})", ephemeral=True)


class SkillCatDeleteSelect(discord.ui.Select):
    def __init__(self):
        cats = load_skill_cats()
        options = []
        for c in cats[:25]:
            options.append(discord.SelectOption(label=c.get("name","?")[:100], value=c["id"]))
        if not options:
            options = [discord.SelectOption(label="ไม่มีหมวด", value="none")]
        super().__init__(placeholder="เลือกหมวดที่จะลบ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        cid = self.values[0]
        cats = load_skill_cats()
        before = len(cats)
        cats = [c for c in cats if c["id"] != cid]
        if len(cats) == before:
            await ix.response.send_message("❌ ไม่พบหมวด", ephemeral=True); return
        save_skill_cats(cats)
        await ix.response.edit_message(content=f"ลบหมวด `{cid}` แล้ว", view=None)


class SkillCatAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="เพิ่มหมวด", style=discord.ButtonStyle.success, row=0)
    async def b_add(self, ix, _b):
        await ix.response.send_modal(SkillCatAddModal())

    @discord.ui.button(label="แก้หมวด", style=discord.ButtonStyle.primary, row=0)
    async def b_edit(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(SkillCatEditSelect())
        await ix.response.send_message("เลือกหมวดที่จะแก้", view=v, ephemeral=True)

    @discord.ui.button(label="ลบหมวด", style=discord.ButtonStyle.danger, row=0)
    async def b_del(self, ix, _b):
        v = discord.ui.View(timeout=180); v.add_item(SkillCatDeleteSelect())
        await ix.response.send_message("เลือกหมวดที่จะลบ", view=v, ephemeral=True)


# ── Admin: Grant skill-creation permission ───────────────────
class GrantSkillCategorySelect(discord.ui.Select):
    def __init__(self, parent):
        cats = load_skill_cats()
        options = [discord.SelectOption(label="ทุกหมวด (any)", value="any",
                                        description="ผู้รับเลือกหมวดได้เอง")]
        for c in cats[:24]:
            options.append(discord.SelectOption(
                label=c.get("name","?")[:100],
                value=c["id"],
                description=(c.get("description","")[:80] or "—"),
            ))
        super().__init__(placeholder="เลือกหมวด...", options=options)
        self.parent_view = parent

    async def callback(self, ix: discord.Interaction):
        self.parent_view.category_id = self.values[0]
        label = "ทุกหมวด" if self.values[0] == "any" else (get_skill_cat(self.values[0]) or {}).get("name", "?")
        await ix.response.send_message(f"✅ เลือกหมวด: **{label}**", ephemeral=True, delete_after=3)


class GrantSkillUserSelect(discord.ui.UserSelect):
    def __init__(self, parent):
        super().__init__(placeholder="เลือกผู้รับ (หลายคนได้)...", min_values=1, max_values=25)
        self.parent_view = parent

    async def callback(self, ix: discord.Interaction):
        targets = [u for u in self.values if not u.bot]
        if not targets:
            await ix.response.send_message("❌ ไม่มีผู้รับที่ใช้ได้", ephemeral=True); return
        self.parent_view.targets = targets
        names = ", ".join(u.display_name for u in targets[:25])
        await ix.response.send_message(f"✅ ผู้รับ: {names}", ephemeral=True, delete_after=3)


class GrantSkillQtyModal(discord.ui.Modal, title="จำนวนสิทธิ์ที่จะให้"):
    f_qty = discord.ui.TextInput(label="กี่สิทธิ์/คน?", placeholder="1", max_length=4)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, ix: discord.Interaction):
        v = self.parent_view
        if not v.targets or not v.category_id:
            await ix.response.send_message("❌ ต้องเลือกหมวด + ผู้รับก่อน", ephemeral=True); return
        qty = max(1, _parse_int(self.f_qty.value, 1) or 1)
        cat_label = "ทุกหมวด" if v.category_id == "any" else (get_skill_cat(v.category_id) or {}).get("name", "?")
        # บันทึก grants ก่อน (เร็ว)
        for target in v.targets:
            grant_skill_slot(str(target.id), v.category_id, qty)
        # respond ทันที กัน interaction timeout
        names = ", ".join(t.display_name for t in v.targets[:25])
        await ix.response.send_message(
            f"✅ ให้สิทธิ์ **{qty}** ครั้ง (หมวด {cat_label}) กับ {len(v.targets)} คน: {names}",
            ephemeral=True,
        )
        # DM หลัง response — fire-and-forget
        for target in v.targets:
            try:
                await target.send(
                    f"🎓 คุณได้รับสิทธิ์สร้างสกิลใหม่ **{qty}** ครั้ง — หมวด **{cat_label}**\n"
                    f"พิมพ์ `/orion` ใน Orion City → กดปุ่ม **สร้างสกิลใหม่**"
                )
            except Exception:
                pass


class GrantSkillSubmitBtn(discord.ui.Button):
    def __init__(self, parent):
        super().__init__(label="ระบุจำนวน + ส่งสิทธิ์", style=discord.ButtonStyle.success, row=2)
        self.parent_view = parent

    async def callback(self, ix: discord.Interaction):
        v = self.parent_view
        if not v.targets or not v.category_id:
            await ix.response.send_message("❌ ต้องเลือกหมวด + ผู้รับก่อน", ephemeral=True); return
        await ix.response.send_modal(GrantSkillQtyModal(v))


class GrantSkillView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.category_id = None
        self.targets = []
        self.add_item(GrantSkillCategorySelect(self))
        self.add_item(GrantSkillUserSelect(self))
        self.add_item(GrantSkillSubmitBtn(self))

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True


class OrionAdminView(discord.ui.View):
    """Main admin hub — ReQuest-style menu"""
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=0)
    async def btn_done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="Skills", style=discord.ButtonStyle.primary, row=1)
    async def btn_skills_menu(self, ix, _b):
        embed = make_menu_embed(
            "Orion Admin — Skills",
            [
                ("เพิ่มสกิลให้ผู้เล่น", "เลือกผู้เล่น (หลายคน) แล้วกรอกข้อมูลสกิล — แจกพร้อมกัน"),
                ("แก้ไขสกิล", "เลือกผู้เล่น → เลือกสกิล → แก้ไขชื่อ/icon/คำอธิบาย/หมวด"),
                ("ลบสกิล", "เลือกผู้เล่น → เลือกสกิลที่จะลบ"),
                ("จัดการหมวดสกิล", "เพิ่ม/แก้/ลบหมวดสกิล (เช่น False Magic, Aura)"),
                ("ให้สิทธิ์สร้างสกิล", "ให้ผู้เล่นสร้างสกิลเองได้ — เลือกหมวด + คนรับ + จำนวน"),
            ],
            color=0x6c5ce7,
        )
        await ix.response.edit_message(embed=embed, view=AdminSkillsSubView())

    @discord.ui.button(label="Players", style=discord.ButtonStyle.primary, row=2)
    async def btn_players_menu(self, ix, _b):
        embed = make_menu_embed(
            "Orion Admin — Players",
            [
                ("ดูโปรไฟล์ผู้เล่น", "ดูโปรไฟล์ตัวละครแบบ OrionProfileView (Admin View)"),
                ("ดูข้อมูลผู้เล่น", "ดูสรุป + สกิลแบบเต็มของผู้เล่น"),
                ("ลบข้อมูลผู้เล่น", "ลบข้อมูลทั้งหมดของผู้เล่นแบบถาวร (ย้อนกลับไม่ได้)"),
                ("คำขอแก้สกิล", "ตรวจสอบคำขอแก้สกิลจากผู้เล่น (อนุมัติ/ปฏิเสธ)"),
            ],
            color=0x6c5ce7,
        )
        await ix.response.edit_message(embed=embed, view=AdminPlayersSubView())


class AdminSkillsSubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix, _b):
        await ix.response.edit_message(embed=_build_orion_admin_embed(), view=OrionAdminView())

    @discord.ui.button(label="เพิ่มสกิลให้ผู้เล่น", style=discord.ButtonStyle.success, row=1)
    async def b1(self, ix, _b):
        await ix.response.send_message("เลือกผู้เล่นที่จะเพิ่มสกิล", view=OrionAddSkillView(), ephemeral=True)

    @discord.ui.button(label="แก้ไขสกิล", style=discord.ButtonStyle.primary, row=2)
    async def b2(self, ix, _b):
        await ix.response.send_message("เลือกผู้เล่นที่จะแก้สกิล", view=OrionEditSkillView(), ephemeral=True)

    @discord.ui.button(label="ลบสกิล", style=discord.ButtonStyle.danger, row=3)
    async def b3(self, ix, _b):
        await ix.response.send_message("เลือกผู้เล่นที่จะลบสกิล", view=OrionDeleteSkillView(), ephemeral=True)

    @discord.ui.button(label="จัดการหมวดสกิล", style=discord.ButtonStyle.primary, row=4)
    async def b4(self, ix, _b):
        cats = load_skill_cats()
        lines = []
        for c in cats:
            icon_part = f"[icon]({c['icon_url']}) " if c.get("icon_url") else f"{c.get('emoji','✨')} "
            lines.append(f"`{c['id']}` — {icon_part}**{c.get('name','?')}** _{c.get('description','')[:60]}_")
        embed = discord.Embed(
            title="จัดการหมวดสกิล",
            description=f"_หมวดในระบบ {len(cats)} หมวด_\n\n" + "\n".join(lines),
            color=0x6c5ce7,
        )
        await ix.response.send_message(embed=embed, view=SkillCatAdminView(), ephemeral=True)


class AdminGrantSkillBtn(discord.ui.Button):
    """โผล่ใน sub-view ของ players (กดแล้วเปิด grant view)"""
    def __init__(self, row=4):
        super().__init__(label="ให้สิทธิ์สร้างสกิล", style=discord.ButtonStyle.success, row=row)

    async def callback(self, ix):
        embed = make_menu_embed(
            "ให้สิทธิ์สร้างสกิล",
            [("วิธีใช้", "เลือก **หมวด** + **ผู้รับ** (หลายคน) → กดปุ่มระบุจำนวน · ผู้รับจะได้รับ DM แจ้งให้ใช้ `/orion` → ปุ่มสร้างสกิลใหม่")],
            color=0x6c5ce7,
        )
        await ix.response.send_message(embed=embed, view=GrantSkillView(), ephemeral=True)


class AdminPlayersSubView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(AdminGrantSkillBtn(row=4))

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="← Back", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix, _b):
        await ix.response.edit_message(embed=_build_orion_admin_embed(), view=OrionAdminView())

    @discord.ui.button(label="ดูโปรไฟล์ผู้เล่น", style=discord.ButtonStyle.primary, row=1)
    async def b0(self, ix, _b):
        await ix.response.send_message("เลือกผู้เล่นที่จะดูโปรไฟล์ (Admin View)", view=AdminViewProfileView(), ephemeral=True)

    @discord.ui.button(label="ดูข้อมูลผู้เล่น", style=discord.ButtonStyle.secondary, row=2)
    async def b1(self, ix, _b):
        await ix.response.send_message("เลือกผู้เล่นที่จะดู", view=OrionViewPlayerView(), ephemeral=True)

    @discord.ui.button(label="ลบข้อมูลผู้เล่น", style=discord.ButtonStyle.danger, row=3)
    async def b2(self, ix, _b):
        await ix.response.send_message("⚠️ เลือกผู้เล่นที่จะ **ลบข้อมูลทั้งหมด** (ย้อนกลับไม่ได้)",
                                       view=OrionDeletePlayerView(), ephemeral=True)

    @discord.ui.button(label="คำขอแก้สกิล", style=discord.ButtonStyle.primary, row=3)
    async def b3(self, ix, _b):
        pending = [r for r in load_skill_requests() if r.get("status") == "pending"]
        embed = make_menu_embed(
            "คำขอแก้สกิล",
            [("คำขอค้าง", f"_คำขอที่ค้างรอการอนุมัติ_  `{len(pending)}` รายการ")],
            color=0xfdcb6e,
        )
        view = discord.ui.View(timeout=300)
        view.add_item(SkillRequestPickSelect())
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


def _build_orion_admin_embed() -> discord.Embed:
    data  = load_orion_players()
    total = len(data)
    return make_menu_embed(
        f"Orion Admin — Main Menu",
        [
            f"_ผู้เล่นในระบบ_  `{total}` _คน_",
            ("Skills", "จัดการสกิลผู้เล่น — เพิ่ม/แก้/ลบ · ตั้งหมวดสกิล · ให้สิทธิ์สร้าง"),
            ("Players", "ดู/ลบข้อมูลผู้เล่น · ตรวจสอบคำขอแก้สกิล"),
        ],
        color=0x6c5ce7,
    )


@bot.tree.command(
    name="orionแอดมิน",
    description="[Admin] เปิดเมนูจัดการ Orion (เห็นเฉพาะคุณ)",
    guild=_ORION_GUILD_OBJ,
)
async def orion_profile_admin_slash(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    await interaction.response.send_message(
        embed=_build_orion_admin_embed(),
        view=OrionAdminView(),
        ephemeral=True,
    )


# ── Admin: skill edit request review ─────────────────────────
class SkillRequestPickSelect(discord.ui.Select):
    def __init__(self):
        reqs = [r for r in load_skill_requests() if r.get("status") == "pending"][:25]
        options = []
        for r in reqs:
            ts = datetime.datetime.fromtimestamp(r.get("created_at", 0)).strftime("%m-%d %H:%M")
            user = bot.get_user(int(r["uid"])) if r["uid"].isdigit() else None
            uname = user.display_name if user else f"User {r['uid']}"
            options.append(discord.SelectOption(
                label=f"{r['skill_name'][:50]} — {uname[:30]}"[:100],
                value=r["id"],
                description=f"{ts} · {r['message'][:50]}"[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีคำขอค้าง", value="none")]
        super().__init__(placeholder="เลือกคำขอ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        rid = self.values[0]
        reqs = load_skill_requests()
        r = next((x for x in reqs if x["id"] == rid), None)
        if not r:
            await ix.response.send_message("❌ ไม่พบคำขอ", ephemeral=True); return
        embed = discord.Embed(
            title=f"คำขอแก้สกิล: {r['skill_name']}",
            description=f"**ผู้ขอ:** <@{r['uid']}>\n\n{r['message']}",
            color=0xfdcb6e,
        )
        embed.set_footer(text=f"ID: {rid}")
        await ix.response.send_message(embed=embed, view=SkillRequestResolveView(rid), ephemeral=True)


class SkillRequestResolveView(discord.ui.View):
    def __init__(self, rid: str):
        super().__init__(timeout=300)
        self.rid = rid

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    async def _resolve(self, ix, approved: bool, note: str = ""):
        reqs = load_skill_requests()
        r = next((x for x in reqs if x["id"] == self.rid), None)
        if not r or r.get("status") != "pending":
            await ix.response.send_message("❌ คำขอนี้ปิดไปแล้ว", ephemeral=True); return
        r["status"] = "approved" if approved else "rejected"
        r["resolved_at"] = int(time.time())
        r["admin_note"] = note
        save_skill_requests(reqs)
        # DM ผู้ขอ
        try:
            user = await bot.fetch_user(int(r["uid"]))
            verdict = "✅ อนุมัติ" if approved else "❌ ปฏิเสธ"
            msg = (
                f"**คำขอแก้สกิลของคุณ:** **{verdict}**\n"
                f"สกิล: **{r['skill_name']}**\n"
                f"คำขอเดิม: {r['message'][:300]}\n"
            )
            if note:
                msg += f"\n**ข้อความจากแอดมิน:** {note}"
            if approved:
                msg += "\n_หาก approve แล้ว แอดมินจะตามไปแก้ในระบบให้_"
            await user.send(msg)
        except Exception:
            pass
        await ix.response.edit_message(
            content=f"{'✅ อนุมัติ' if approved else '❌ ปฏิเสธ'}คำขอ `{self.rid}` แล้ว — DM ผู้ขอแล้ว",
            embed=None, view=None,
        )

    @discord.ui.button(label="อนุมัติ", style=discord.ButtonStyle.success)
    async def b_yes(self, ix, _b):
        await ix.response.send_modal(_SkillRequestNoteModal(self.rid, True))

    @discord.ui.button(label="ปฏิเสธ", style=discord.ButtonStyle.danger)
    async def b_no(self, ix, _b):
        await ix.response.send_modal(_SkillRequestNoteModal(self.rid, False))


class _SkillRequestNoteModal(discord.ui.Modal, title="ข้อความถึงผู้ขอ (ไม่บังคับ)"):
    f_note = discord.ui.TextInput(label="ข้อความ", style=discord.TextStyle.paragraph, required=False, max_length=500)

    def __init__(self, rid: str, approved: bool):
        super().__init__()
        self.rid = rid
        self.approved = approved

    async def on_submit(self, ix: discord.Interaction):
        view = SkillRequestResolveView(self.rid)
        await view._resolve(ix, self.approved, self.f_note.value.strip())


@bot.tree.command(name="คำขอสกิล", description="[Admin] ดูคำขอแก้สกิลที่ค้างอยู่", guild=_ORION_GUILD_OBJ)
async def cmd_skill_requests(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    pending = [r for r in load_skill_requests() if r.get("status") == "pending"]
    embed = discord.Embed(
        title="คำขอแก้สกิล",
        description=f"_คำขอค้าง **{len(pending)}** อัน_",
        color=0xfdcb6e,
    )
    view = discord.ui.View(timeout=300)
    view.add_item(SkillRequestPickSelect())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ── Artifact Skill Transfer (โอนสกิล) ──────────────────────────

class _SkillTransferSkillSelect(discord.ui.Select):
    def __init__(self, uid: str, author):
        self.uid = uid
        self.author = author
        data = load_orion_players()
        skills = data.get(uid, {}).get("skills", [])
        cats = load_skill_cats()
        transferable_cats = {c["id"] for c in cats if c.get("transferable")}
        transferable = [
            (i, s) for i, s in enumerate(skills)
            if s.get("transferable") or s.get("category") in transferable_cats
        ]
        options = []
        for i, s in transferable[:25]:
            cat_label = s.get("category") or s.get("origin_type") or "—"
            options.append(discord.SelectOption(
                label=s.get("name", "?")[:100],
                value=str(i),
                description=f"{cat_label} · {s.get('description', s.get('context', ''))[:60] or '—'}",
                emoji=s.get("icon") or s.get("emoji") or "⚙️",
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสกิลที่โอนได้", value="none")]
        super().__init__(placeholder="เลือกสกิลที่จะโอน...", options=options)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return
        if self.values[0] == "none":
            await ix.response.defer(); return
        skill_index = int(self.values[0])
        data = load_orion_players()
        skills = data.get(self.uid, {}).get("skills", [])
        if skill_index >= len(skills):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        skill = skills[skill_index]
        await ix.response.edit_message(
            content=f"📤 โอนสกิล **{skill.get('name','?')}** — เลือกผู้รับ ↓",
            view=_SkillTransferRecipientView(self.uid, self.author, skill_index),
        )


class _SkillTransferView(discord.ui.View):
    def __init__(self, uid: str, author):
        super().__init__(timeout=180)
        self.add_item(_SkillTransferSkillSelect(uid, author))


class _SkillTransferUserSelect(discord.ui.UserSelect):
    def __init__(self, sender_uid: str, skill_index: int):
        self.sender_uid = sender_uid
        self.skill_index = skill_index
        super().__init__(placeholder="👤 เลือกผู้รับสกิล...", min_values=1, max_values=1)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.sender_uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ โอนให้บอทไม่ได้", ephemeral=True); return
        if target.id == int(self.sender_uid):
            await ix.response.send_message("❌ โอนให้ตัวเองไม่ได้", ephemeral=True); return
        data = load_orion_players()
        skills = data.get(self.sender_uid, {}).get("skills", [])
        if self.skill_index >= len(skills):
            await ix.response.send_message("❌ ไม่พบสกิล", ephemeral=True); return
        skill = skills[self.skill_index]
        await ix.response.edit_message(
            content=(
                f"⚠️ ยืนยันโอนสกิล **{skill.get('name','?')}** ให้ **{target.display_name}**?\n"
                f"_(สกิลนี้จะถูก**ลบออก**จากคุณ และ**โอนให้**ผู้รับ — ไม่สามารถยกเลิกได้)_"
            ),
            view=_SkillTransferConfirmView(self.sender_uid, str(target.id), target.display_name, self.skill_index),
        )


class _SkillTransferRecipientView(discord.ui.View):
    def __init__(self, uid: str, author, skill_index: int):
        super().__init__(timeout=120)
        self.add_item(_SkillTransferUserSelect(uid, skill_index))


class _SkillTransferConfirmView(discord.ui.View):
    def __init__(self, sender_uid: str, recv_uid: str, recv_name: str, skill_index: int):
        super().__init__(timeout=60)
        self.sender_uid = sender_uid
        self.recv_uid = recv_uid
        self.recv_name = recv_name
        self.skill_index = skill_index

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if str(ix.user.id) != self.sender_uid:
            await ix.response.send_message("❌ ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="✅ ยืนยันโอน", style=discord.ButtonStyle.danger, row=0)
    async def btn_confirm(self, ix: discord.Interaction, _b):
        data = load_orion_players()
        skills = data.get(self.sender_uid, {}).get("skills", [])
        if self.skill_index >= len(skills):
            await ix.response.edit_message(content="❌ ไม่พบสกิล", view=None); return
        skill = skills[self.skill_index]
        # remove from sender
        data[self.sender_uid]["skills"] = [s for i, s in enumerate(skills) if i != self.skill_index]
        # add to recipient
        ensure_orion_player(self.recv_uid)
        data = load_orion_players()
        data[self.recv_uid].setdefault("skills", []).append(skill)
        save_orion_players(data)
        await ix.response.edit_message(
            content=f"✅ โอนสกิล **{skill.get('name','?')}** ให้ **{self.recv_name}** สำเร็จ",
            view=None,
        )
        try:
            recv_user = await bot.fetch_user(int(self.recv_uid))
            await recv_user.send(
                f"⚙️ คุณได้รับสกิล **{skill.get('name','?')}** จาก <@{self.sender_uid}>"
            )
        except Exception:
            pass
        # logs
        try:
            skill_name = skill.get("name", "?")
            await orion_logs.log_action(self.sender_uid, "skill_transfer_send", skill=skill_name, to_uid=self.recv_uid)
            await orion_logs.log_action(self.recv_uid, "skill_transfer_recv", skill=skill_name, from_uid=self.sender_uid)
        except Exception:
            pass

    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cancel(self, ix: discord.Interaction, _b):
        await ix.response.edit_message(content="❌ ยกเลิกการโอนสกิล", view=None)


@bot.tree.command(name="โอนสกิล", description="โอน Artifact Skill ให้ผู้เล่นคนอื่น (เฉพาะสกิลที่โอนได้)", guild=_ORION_GUILD_OBJ)
async def cmd_transfer_skill(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    data = load_orion_players()
    skills = data.get(uid, {}).get("skills", [])
    cats = load_skill_cats()
    transferable_cats = {c["id"] for c in cats if c.get("transferable")}
    has_transferable = any(
        s.get("transferable") or s.get("category") in transferable_cats
        for s in skills
    )
    if not has_transferable:
        await interaction.response.send_message(
            "❌ คุณไม่มีสกิลที่สามารถโอนได้\n"
            "_(เฉพาะ Artifact Skill จากระบบ Creation เท่านั้นที่โอนได้)_",
            ephemeral=True,
        ); return
    await interaction.response.send_message(
        "⚙️ เลือกสกิลที่ต้องการโอน ↓",
        view=_SkillTransferView(uid, interaction.user),
        ephemeral=True,
    )


# ── End Artifact Skill Transfer ──────────────────────────────


@bot.command(name="orionแอดมิน", aliases=["orionprofileadmin", "orionprofileadm"])
@commands.has_permissions(administrator=True)
async def orion_profile_admin_cmd(ctx):
    if not is_orion_guild(ctx):
        return
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound, AttributeError):
        pass
    await ctx.send(
        embed=_build_orion_admin_embed(),
        view=OrionAdminView(),
        delete_after=300,
    )


@orion_profile_admin_cmd.error
async def orion_profile_admin_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ คำสั่งนี้ใช้ได้เฉพาะ Admin เท่านั้น", delete_after=8)


HELP_CATEGORIES["Orion — Character Profile"] = {
    "emoji": "◈", "guild": ORION_GUILD_ID,
    "desc": "ระบบโปรไฟล์ตัวละครของ Orion — สกิล / กระเป๋า / รูป / รูปลักษณ์",
    "commands": [
        ("?orion",         "◈ โปรไฟล์ตัวละคร — สกิล · กระเป๋า · รูป · รูปลักษณ์"),
        ("?orionแอดมิน",  "🔒 [Admin] จัดการสกิล / ไอเทม / ดูข้อมูลผู้เล่น"),
    ],
}


# ████████████████████████████████████████████████████████████
# ████  CURRENCY / ITEMS / CRAFT / GUILD SYSTEMS  ████████████
# ████████████████████████████████████████████████████████████

import uuid as _orion_uuid

CURRENCY_FILE = f"{ORION_DATA_DIR}/currency.json"
GUILDS_FILE   = f"{ORION_DATA_DIR}/guilds.json"
# หมายเหตุ: ITEMS_FILE, DEFAULT_ITEMS, _slugify ย้ายไปอยู่ใน orion_items.py แล้ว

DEFAULT_CURRENCY = {
    "name": "Aurum",
    "emoji": "💰",
    "icon_url": "",
    "start_balance": 100,
    "guild_create_cost": 100,
    "guild_slot_cost": 50,
}

MINIGAME_LABELS = {
    "guess_number": "🎲 ทายเลข 1-20 (5 ครั้ง)",
    "math_quick":   "🧮 คิดเลขเร็ว (3 ข้อ)",
    "click_target": "🎯 กดปุ่มเป้าหมาย (3 รอบ)",
    "anagram":      "🔤 จัดเรียงคำ (English)",
    "odd_one_out":  "🔍 หาตัวที่ต่าง (3 รอบ)",
    "rps":          "✊ เป่ายิ้งฉุบ (best of 3)",
    "number_sort":  "🔢 เรียงตัวเลข 1→4 (น้อย→มาก)",
    "emoji_count":  "🔎 นับ emoji ในแถว",
}
MINIGAME_KEYS = list(MINIGAME_LABELS.keys())


# ── CURRENCY ──────────────────────────────────────────────────
def load_currency_cfg() -> dict:
    cfg = load_json(CURRENCY_FILE, {})
    changed = False
    for k, v in DEFAULT_CURRENCY.items():
        if k not in cfg:
            cfg[k] = v; changed = True
    if changed:
        save_currency_cfg(cfg)
    return cfg


def save_currency_cfg(cfg: dict):
    save_json(CURRENCY_FILE, cfg)


def money_str(amount: int) -> str:
    cfg = load_currency_cfg()
    return f"{cfg['emoji']} **{int(amount):,}** {cfg['name']}"


def get_wallet(uid: str) -> int:
    ensure_orion_player(uid)
    return int(load_orion_players().get(uid, {}).get("wallet", 0))


def set_wallet(uid: str, amount: int):
    ensure_orion_player(uid)
    data = load_orion_players()
    data[uid]["wallet"] = max(0, int(amount))
    save_orion_players(data)


def add_money(uid: str, delta: int) -> int:
    """+ เพิ่ม / - ลด — return ยอดใหม่ หรือ -1 ถ้าเงินไม่พอ"""
    cur = get_wallet(uid)
    new = cur + int(delta)
    if new < 0:
        return -1
    set_wallet(uid, new)
    return new


def _parse_int(s: str, default=None):
    try:
        return int(str(s).strip())
    except Exception:
        return default


class CurrencySettingsModal(discord.ui.Modal, title="⚙️ ตั้งค่าเงิน"):
    f_name        = discord.ui.TextInput(label="ชื่อค่าเงิน", placeholder="เช่น Aurum / Gold", max_length=30)
    f_emoji       = discord.ui.TextInput(label="Emoji", placeholder="💰 🪙 💎", max_length=10)
    f_icon        = discord.ui.TextInput(label="Icon URL (ไม่บังคับ)", required=False, max_length=400)
    f_start       = discord.ui.TextInput(label="เงินเริ่มต้นของผู้เล่นใหม่", placeholder="100", max_length=10)
    f_guild_cost  = discord.ui.TextInput(label="ราคาสร้างกิลด์ / ราคาเพิ่ม slot (คั่นด้วย ,)", placeholder="100, 50", max_length=20)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_currency_cfg()
        cfg["name"]     = (self.f_name.value or "Aurum").strip()
        cfg["emoji"]    = (self.f_emoji.value or "💰").strip()
        cfg["icon_url"] = (self.f_icon.value or "").strip()
        cfg["start_balance"] = max(0, _parse_int(self.f_start.value, 100) or 100)
        parts = [p.strip() for p in (self.f_guild_cost.value or "100,50").split(",")]
        cfg["guild_create_cost"] = max(0, _parse_int(parts[0] if parts else "100", 100) or 100)
        cfg["guild_slot_cost"]   = max(0, _parse_int(parts[1] if len(parts) > 1 else "50", 50) or 50)
        save_currency_cfg(cfg)
        await interaction.response.send_message(
            f"✅ ตั้งค่าเงินเป็น {cfg['emoji']} **{cfg['name']}** | เริ่มต้น {cfg['start_balance']} | กิลด์ {cfg['guild_create_cost']} / slot {cfg['guild_slot_cost']}",
            ephemeral=True,
        )


class CurrencyAmountModal(discord.ui.Modal, title="🎁 ระบุจำนวนเงิน"):
    f_amount = discord.ui.TextInput(label="จำนวน (+ เพิ่ม / - ลด) — แจกทุกคนเท่ากัน", placeholder="100", max_length=10)

    def __init__(self, target_uids: list, target_names: list):
        super().__init__()
        self.target_uids = target_uids
        self.target_names = target_names

    async def on_submit(self, interaction: discord.Interaction):
        amt = _parse_int(self.f_amount.value)
        if amt is None:
            await interaction.response.send_message("❌ จำนวนต้องเป็นตัวเลข", ephemeral=True); return
        ok, fail = [], []
        for uid, name in zip(self.target_uids, self.target_names):
            new = add_money(uid, amt)
            if new < 0:
                fail.append(name)
            else:
                ok.append(f"{name} ({new:,})")
        action = "เพิ่ม" if amt > 0 else "ลด"
        lines = [f"✅ {action} {abs(amt):,} ให้ **{len(ok)}** คน"]
        if ok:
            lines.append("• " + " · ".join(ok[:25]))
        if fail:
            lines.append(f"❌ ล้มเหลว {len(fail)}: " + ", ".join(fail[:10]))
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)


class CurrencyGiveUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(placeholder="👤 เลือกผู้เล่น (เลือกได้หลายคน)...", min_values=1, max_values=25)

    async def callback(self, ix: discord.Interaction):
        targets = [u for u in self.values if not u.bot]
        if not targets:
            await ix.response.send_message("❌ ไม่มีผู้เล่นที่ใช้ได้", ephemeral=True); return
        uids = [str(u.id) for u in targets]
        names = [u.display_name for u in targets]
        await ix.response.send_modal(CurrencyAmountModal(uids, names))


class CurrencyGiveView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(CurrencyGiveUserSelect())


class ServerEmojiSelect(discord.ui.Select):
    """Dropdown รายชื่อ emoji ของเซิร์ฟ (max 25)"""
    def __init__(self, guild: discord.Guild):
        emojis = list(guild.emojis)[:25] if guild else []
        options = []
        for e in emojis:
            options.append(discord.SelectOption(
                label=e.name[:100],
                value=str(e),   # <:name:id> หรือ <a:name:id>
                emoji=e,
            ))
        if not options:
            options = [discord.SelectOption(label="(เซิร์ฟนี้ไม่มี custom emoji)", value="none")]
        super().__init__(placeholder="เลือก emoji ของเซิร์ฟ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        cfg = load_currency_cfg()
        cfg["emoji"] = self.values[0]
        cfg["icon_url"] = ""   # ทับ icon URL ถ้าเคยตั้ง
        save_currency_cfg(cfg)
        await ix.response.edit_message(
            content=f"✅ ตั้ง emoji ค่าเงินเป็น {self.values[0]} แล้ว",
            view=None,
        )


class CurrencyIconURLModal(discord.ui.Modal, title="🖼️ ใช้ URL รูปเป็น icon ค่าเงิน"):
    f_url = discord.ui.TextInput(label="URL รูป (https://...)", max_length=400)

    async def on_submit(self, ix: discord.Interaction):
        url = (self.f_url.value or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            await ix.response.send_message("❌ ต้องเป็น URL", ephemeral=True); return
        cfg = load_currency_cfg()
        cfg["icon_url"] = url
        # คง emoji เดิมสำหรับใช้ inline
        save_currency_cfg(cfg)
        await ix.response.send_message(f"✅ ตั้ง icon URL แล้ว — embed จะใช้รูปนี้เป็น thumbnail", ephemeral=True)


class CurrencyUnicodeModal(discord.ui.Modal, title="🪙 ใช้ Unicode emoji"):
    f_emoji = discord.ui.TextInput(label="Emoji (วาง emoji unicode เช่น 💰 🪙 💎)", max_length=10)

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_currency_cfg()
        cfg["emoji"] = (self.f_emoji.value or "💰").strip() or "💰"
        save_currency_cfg(cfg)
        await ix.response.send_message(f"✅ ตั้ง emoji เป็น {cfg['emoji']}", ephemeral=True)


class CurrencyIconPickerView(discord.ui.View):
    def __init__(self, guild):
        super().__init__(timeout=300)
        self.add_item(ServerEmojiSelect(guild))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ใช้ Unicode emoji", style=discord.ButtonStyle.secondary, row=1)
    async def btn_unicode(self, ix, _b):
        await ix.response.send_modal(CurrencyUnicodeModal())

    @discord.ui.button(label="ใช้ URL รูป", style=discord.ButtonStyle.secondary, row=1)
    async def btn_url(self, ix, _b):
        await ix.response.send_modal(CurrencyIconURLModal())


class CurrencyAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=0)
    async def btn_done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="Settings", style=discord.ButtonStyle.primary, row=1)
    async def btn_settings(self, interaction, button):
        cfg = load_currency_cfg()
        modal = CurrencySettingsModal()
        modal.f_name.default       = cfg["name"]
        modal.f_emoji.default      = cfg["emoji"]
        modal.f_icon.default       = cfg["icon_url"]
        modal.f_start.default      = str(cfg["start_balance"])
        modal.f_guild_cost.default = f"{cfg['guild_create_cost']}, {cfg['guild_slot_cost']}"
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Icon", style=discord.ButtonStyle.primary, row=2)
    async def btn_icon(self, interaction, button):
        guild = interaction.guild
        embed = make_menu_embed(
            "Currency Icon",
            [
                ("Server Emoji", "เลือก custom emoji ของเซิร์ฟจาก dropdown ด้านล่าง"),
                ("Unicode emoji", "กรอก emoji ปกติ (เช่น 💰 🪙 💎)"),
                ("URL รูป", "วาง URL รูปภาพ — ใช้เป็น thumbnail ใน embed"),
            ],
            color=0xf1c40f,
        )
        await interaction.response.send_message(embed=embed, view=CurrencyIconPickerView(guild), ephemeral=True)

    @discord.ui.button(label="Give / Take", style=discord.ButtonStyle.success, row=3)
    async def btn_give(self, interaction, button):
        await interaction.response.send_message(
            "เลือกผู้เล่นจาก dropdown (เลือกได้หลายคน)",
            view=CurrencyGiveView(),
            ephemeral=True,
        )


@bot.tree.command(name="เงิน", description="ดูเงินของตัวเอง", guild=_ORION_GUILD_OBJ)
async def cmd_wallet(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    cfg = load_currency_cfg()
    bal = get_wallet(uid)
    embed = discord.Embed(
        title=f"{cfg['emoji']}  กระเป๋าเงินของคุณ",
        description=f"ยอดคงเหลือ: {money_str(bal)}",
        color=0xf1c40f,
    )
    if cfg.get("icon_url"):
        embed.set_thumbnail(url=cfg["icon_url"])
    embed.set_footer(text=f"Orion · {cfg['name']} Wallet")
    await interaction.response.send_message(embed=embed, ephemeral=_eph("เงิน"))


@bot.tree.command(name="เงินแอดมิน", description="[Admin] ตั้งค่าและจัดการเงิน", guild=_ORION_GUILD_OBJ)
async def cmd_wallet_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    cfg = load_currency_cfg()
    embed = make_menu_embed(
        f"Currency Admin — {cfg['name']}",
        [
            f"_ค่าเงินปัจจุบัน_  {cfg['emoji']} **{cfg['name']}**  ·  _เริ่มต้น_  `{cfg['start_balance']:,}`",
            ("Settings", "ตั้งชื่อค่าเงิน / เงินเริ่มต้น / ราคา guild / ราคา slot"),
            ("Icon", "เลือก icon เป็น server emoji, unicode, หรือ URL รูป"),
            ("Give / Take", "แจกหรือยึดเงินผู้เล่น (เลือกหลายคนได้)"),
        ],
        color=0xf1c40f,
    )
    if cfg.get("icon_url"):
        embed.set_thumbnail(url=cfg["icon_url"])
    await interaction.response.send_message(embed=embed, view=CurrencyAdminView(), ephemeral=True)


# ── เช็คเงิน / โอนเงิน ────────────────────────────────────────
@bot.tree.command(name="เช็คเงิน", description="ดูเงินของผู้เล่นคนอื่น (หรือของตัวเอง)", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(target="ผู้เล่นที่จะดู — ว่าง = ดูของตัวเอง")
async def cmd_check_money(interaction: discord.Interaction, target: discord.Member = None):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    target = target or interaction.user
    if target.bot:
        await interaction.response.send_message("❌ ดูเงินของบอทไม่ได้", ephemeral=True); return
    cfg = load_currency_cfg()
    bal = get_wallet(str(target.id))
    embed = discord.Embed(
        title=f"{cfg['emoji']}  เงินของ {target.display_name}",
        description=f"ยอด: {money_str(bal)}",
        color=0xf1c40f,
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.set_footer(text=f"Orion · {cfg['name']} Wallet")
    await interaction.response.send_message(embed=embed, ephemeral=_eph("เช็คเงิน"))


@bot.tree.command(name="โอนเงิน", description="โอนเงินให้ผู้เล่นคนอื่น", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(target="ผู้รับเงิน", amount="จำนวนเงินที่โอน (ต้องมากกว่า 0)")
async def cmd_transfer_money(interaction: discord.Interaction, target: discord.Member, amount: int):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if amount <= 0:
        await interaction.response.send_message("❌ จำนวนต้องมากกว่า 0", ephemeral=True); return
    if target.id == interaction.user.id:
        await interaction.response.send_message("❌ โอนให้ตัวเองไม่ได้", ephemeral=True); return
    if target.bot:
        await interaction.response.send_message("❌ โอนให้บอทไม่ได้", ephemeral=True); return
    sender = str(interaction.user.id)
    recv   = str(target.id)
    if get_wallet(sender) < amount:
        await interaction.response.send_message(
            f"❌ เงินไม่พอ — มี {money_str(get_wallet(sender))} แต่จะโอน {money_str(amount)}",
            ephemeral=True,
        )
        return
    add_money(sender, -amount)
    add_money(recv, amount)
    cfg = load_currency_cfg()
    embed = discord.Embed(
        title=f"{cfg['emoji']}  โอนเงินสำเร็จ",
        description=(
            f"📤 ผู้ส่ง: {interaction.user.mention}\n"
            f"📥 ผู้รับ: {target.mention}\n"
            f"💸 จำนวน: {money_str(amount)}\n\n"
            f"ยอดคงเหลือของคุณ: {money_str(get_wallet(sender))}"
        ),
        color=0x2ecc71,
    )
    await interaction.response.send_message(embed=embed, ephemeral=_eph("โอนเงิน"))
    # แจ้งผู้รับผ่าน DM ถ้าได้
    try:
        await target.send(
            f"💰 คุณได้รับ {money_str(amount)} จาก **{interaction.user.display_name}** "
            f"(ยอดใหม่: {money_str(get_wallet(recv))})"
        )
    except Exception:
        pass


# ── ITEM SYSTEM (แยกออกไปอยู่ไฟล์ orion_items.py) ────────────
# import โมดูลแยก — register slash commands /ไอเทม /คลังไอเทม /ไอเทมแอดมิน
# พร้อม expose ฟังก์ชันที่ craft section ใช้ผ่าน namespace orion_items.*
import orion_items
from orion_items import (
    load_items_catalog, save_items_catalog, get_item,
    add_player_item, remove_player_item, player_has_items,
    _build_item_embed, _items_overview_embed, _player_bag_embed,
    ItemCatalogView, PlayerBagView,
    _slugify,
)


# ── CRAFT ADMIN — เลือกผลคราฟจาก catalog หรือสร้างใหม่ ────────
def _craft_builder_embed(basics: dict, existing_id: str = None) -> discord.Embed:
    title = f"ออกแบบ recipe — {basics['emoji']} {basics['name']}"
    if existing_id:
        desc = (
            f"**ผลคราฟ:** ไอเทมเดิม `{existing_id}` (จาก catalog)\n\n"
            "• เลือกส่วนผสม (สูงสุด 3) · qty default = 1\n"
            "• กด **ปรับจำนวน** ถ้าอยากแก้ qty\n"
            "• เลือกมินิเกม · กด **บันทึก recipe**"
        )
    else:
        desc = (
            "**ผลคราฟ:** ไอเทมใหม่ (ยังไม่มีใน catalog)\n\n"
            "• เลือกส่วนผสม (สูงสุด 3) · qty default = 1\n"
            "• กด **ปรับจำนวน** ถ้าอยากแก้ qty\n"
            "• เลือกมินิเกม · กด **บันทึก recipe**"
        )
    embed = discord.Embed(title=title, description=desc, color=0xe67e22)
    if basics.get("image_url"):
        embed.set_thumbnail(url=basics["image_url"])
    return embed


_CRAFT_PAGE_SIZE = 24   # เหลือ 1 ช่องให้ "+ สร้างใหม่"


class CraftOutputPickerSelect(discord.ui.Select):
    """Dropdown เลือกผลคราฟ — จาก catalog หรือสร้างใหม่ (paginated)"""
    def __init__(self, page: int = 0):
        self.page = page
        cat = load_items_catalog()
        items = sorted(cat.items(), key=lambda x: x[1].get("name", x[0]).lower())
        total = len(items)
        start = page * _CRAFT_PAGE_SIZE
        end = start + _CRAFT_PAGE_SIZE
        page_items = items[start:end]
        max_page = max(0, (total - 1) // _CRAFT_PAGE_SIZE)

        options = []
        # "+ สร้างใหม่" เฉพาะหน้าแรก (กันสะดวก ไม่ต้องหามาเลือกทุกหน้า)
        if page == 0:
            options.append(discord.SelectOption(
                label="+ สร้างไอเทมใหม่",
                value="__new__",
                description="ไอเทมยังไม่มีใน catalog — กรอกชื่อ/icon/desc/ราคา",
            ))
        room_left = 25 - len(options)
        for iid, it in page_items[:room_left]:
            type_label = it.get("type", "resource")
            options.append(discord.SelectOption(
                label=it.get("name", "?")[:100],
                value=iid,
                description=f"{iid} · {type_label} · ราคา {it.get('sell_price',0):,}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
            ))
        ph = f"เลือกผลคราฟ (หน้า {page+1}/{max_page+1})..." if max_page > 0 else "เลือกผลคราฟ..."
        super().__init__(placeholder=ph, options=options)

    async def callback(self, ix: discord.Interaction):
        v = self.values[0]
        if v == "__new__":
            await ix.response.send_modal(CraftBasicsModal())
            return
        cat = load_items_catalog()
        it = cat.get(v)
        if not it:
            await ix.response.send_message("❌ ไม่พบไอเทม", ephemeral=True); return
        basics = {
            "name":        it.get("name", v),
            "emoji":       it.get("emoji", "🛠️"),
            "image_url":   it.get("image_url", ""),
            "description": it.get("description", ""),
            "sell_price":  int(it.get("sell_price", 0)),
        }
        view = CraftRecipeBuilderView(basics, existing_id=v)
        await ix.response.edit_message(
            content=f"ตั้ง recipe ให้ไอเทมเดิม `{v}`",
            embed=_craft_builder_embed(basics, existing_id=v),
            view=view,
        )


class _CraftOutputNavBtn(discord.ui.Button):
    def __init__(self, parent_view, delta: int, label: str):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=1)
        self.parent_view = parent_view
        self.delta = delta

    async def callback(self, ix: discord.Interaction):
        new_page = self.parent_view.page + self.delta
        new_view = CraftOutputPickerView(page=new_page)
        await ix.response.edit_message(view=new_view)


class CraftOutputPickerView(discord.ui.View):
    def __init__(self, page: int = 0):
        super().__init__(timeout=300)
        self.page = page
        cat = load_items_catalog()
        max_page = max(0, (len(cat) - 1) // _CRAFT_PAGE_SIZE)
        self.add_item(CraftOutputPickerSelect(page=page))
        if page > 0:
            self.add_item(_CraftOutputNavBtn(self, -1, "← หน้าก่อน"))
        if page < max_page:
            self.add_item(_CraftOutputNavBtn(self, +1, "หน้าถัดไป →"))


class CraftBasicsModal(discord.ui.Modal, title="🛠️ ข้อมูลพื้นฐานไอเทมคราฟ"):
    f_name  = discord.ui.TextInput(label="ชื่อไอเทมคราฟ", max_length=60)
    f_emoji = discord.ui.TextInput(label="Emoji (ไม่บังคับ)", placeholder="🛠️ ⚔️ 🏹", required=False, max_length=10)
    f_image = discord.ui.TextInput(label="URL รูปภาพ (ไม่บังคับ)", required=False, max_length=400)
    f_desc  = discord.ui.TextInput(label="รายละเอียด", style=discord.TextStyle.paragraph, max_length=600)
    f_price = discord.ui.TextInput(label="ราคาขาย", placeholder="0", max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        price = max(0, _parse_int(self.f_price.value, 0) or 0)
        basics = {
            "name":        self.f_name.value.strip(),
            "emoji":       (self.f_emoji.value or "🛠️").strip() or "🛠️",
            "image_url":   (self.f_image.value or "").strip(),
            "description": (self.f_desc.value or "").strip(),
            "sell_price":  price,
        }
        view = CraftRecipeBuilderView(basics)
        await interaction.response.send_message(
            embed=_craft_builder_embed(basics),
            view=view,
            ephemeral=True,
        )


_ING_PAGE_SIZE = 23  # เหลือ 2 ช่อง: "(ไม่ใช้)" + "→ หน้าถัดไป"


class CraftIngredientSlotSelect(discord.ui.Select):
    """1 slot สำหรับ 1 ส่วนผสม — paginated ด้วย option "→ หน้าถัดไป" ใน select เอง"""
    def __init__(self, parent_view, slot_idx: int, page: int = 0):
        self.parent_view = parent_view
        self.slot_idx = slot_idx
        self.page = page
        cat = load_items_catalog()
        items = sorted(cat.items(), key=lambda x: x[1].get("name", x[0]).lower())
        total = len(items)
        max_page = max(0, (total - 1) // _ING_PAGE_SIZE)
        start = page * _ING_PAGE_SIZE
        end = start + _ING_PAGE_SIZE
        page_items = items[start:end]

        options = [discord.SelectOption(label="(ไม่ใช้ slot นี้)", value="__none__")]
        for iid, it in page_items:
            options.append(discord.SelectOption(
                label=it.get("name", "?")[:100],
                value=iid,
                description=f"{iid} · ราคา {it.get('sell_price',0):,}"[:80],
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if page < max_page:
            options.append(discord.SelectOption(
                label="→ หน้าถัดไป",
                value=f"__nextpage__:{page+1}",
                description=f"ดูไอเทมหน้า {page+2}/{max_page+1}",
            ))
        if page > 0:
            options.append(discord.SelectOption(
                label="← หน้าก่อน",
                value=f"__nextpage__:{page-1}",
                description=f"กลับหน้า {page}/{max_page+1}",
            ))
        ph_suffix = f" (หน้า {page+1}/{max_page+1})" if max_page > 0 else ""
        super().__init__(
            placeholder=f"ส่วนผสมที่ {slot_idx+1}{ph_suffix}...",
            options=options[:25],
            min_values=1, max_values=1,
            row=slot_idx,
        )

    async def callback(self, ix: discord.Interaction):
        v = self.values[0]
        if v.startswith("__nextpage__:"):
            # rebuild view with new page for this slot
            new_page = int(v.split(":", 1)[1])
            pv = self.parent_view
            pv.slot_pages[self.slot_idx] = new_page
            # rebuild children of this view
            new_view = CraftRecipeBuilderView(pv.basics, existing_id=pv.existing_id, _carry_state=pv)
            await ix.response.edit_message(view=new_view)
            return
        if v == "__none__":
            self.parent_view.ingredients[self.slot_idx] = None
        else:
            existing_qty = 1
            if self.parent_view.ingredients[self.slot_idx]:
                existing_qty = self.parent_view.ingredients[self.slot_idx].get("qty", 1)
            self.parent_view.ingredients[self.slot_idx] = {"item_id": v, "qty": existing_qty}
        await ix.response.send_message(f"✅ บันทึก slot {self.slot_idx+1}", ephemeral=True, delete_after=2)


class CraftMinigameSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view
        options = [discord.SelectOption(label=label, value=key) for key, label in MINIGAME_LABELS.items()]
        super().__init__(placeholder="🎮 เลือกมินิเกม...", options=options, min_values=1, max_values=1, row=3)

    async def callback(self, ix: discord.Interaction):
        self.parent_view.minigame_key = self.values[0]
        await ix.response.send_message(f"✅ มินิเกม: {MINIGAME_LABELS.get(self.values[0])}", ephemeral=True, delete_after=2)


class CraftQtyModal(discord.ui.Modal, title="🔢 ปรับจำนวนส่วนผสม"):
    f_q1 = discord.ui.TextInput(label="จำนวน slot 1", required=False, placeholder="1", max_length=4)
    f_q2 = discord.ui.TextInput(label="จำนวน slot 2", required=False, placeholder="1", max_length=4)
    f_q3 = discord.ui.TextInput(label="จำนวน slot 3", required=False, placeholder="1", max_length=4)

    def __init__(self, parent_view):
        super().__init__()
        self.parent_view = parent_view
        for idx, field in enumerate((self.f_q1, self.f_q2, self.f_q3)):
            ing = parent_view.ingredients[idx]
            if ing:
                field.default = str(ing.get("qty", 1))

    async def on_submit(self, ix: discord.Interaction):
        for idx, field in enumerate((self.f_q1, self.f_q2, self.f_q3)):
            ing = self.parent_view.ingredients[idx]
            if ing:
                q = _parse_int(field.value, 1) or 1
                ing["qty"] = max(1, q)
        await ix.response.send_message("✅ ปรับจำนวนส่วนผสมแล้ว", ephemeral=True, delete_after=3)


class CraftRecipeBuilderView(discord.ui.View):
    def __init__(self, basics: dict, existing_id: str = None, _carry_state=None):
        super().__init__(timeout=600)
        self.basics = basics
        self.existing_id = existing_id
        # carry state ถ้ามี (ตอน rebuild หลังเปลี่ยน page)
        if _carry_state is not None:
            self.ingredients   = _carry_state.ingredients
            self.minigame_key  = _carry_state.minigame_key
            self.slot_pages    = _carry_state.slot_pages
        else:
            self.ingredients = [None, None, None]
            self.minigame_key = None
            self.slot_pages = [0, 0, 0]
        self.add_item(CraftIngredientSlotSelect(self, 0, page=self.slot_pages[0]))
        self.add_item(CraftIngredientSlotSelect(self, 1, page=self.slot_pages[1]))
        self.add_item(CraftIngredientSlotSelect(self, 2, page=self.slot_pages[2]))
        self.add_item(CraftMinigameSelect(self))
        self.add_item(CraftQtyEditBtn(self))
        self.add_item(CraftSaveBtn(self))


class CraftQtyEditBtn(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="ปรับจำนวน", style=discord.ButtonStyle.secondary, row=4)
        self.parent_view = parent_view
    async def callback(self, ix: discord.Interaction):
        await ix.response.send_modal(CraftQtyModal(self.parent_view))


class CraftSaveBtn(discord.ui.Button):
    def __init__(self, parent_view):
        super().__init__(label="บันทึก recipe", style=discord.ButtonStyle.success, row=4)
        self.parent_view = parent_view

    async def callback(self, ix: discord.Interaction):
        v = self.parent_view
        ings = [ing for ing in v.ingredients if ing]
        if not ings:
            await ix.response.send_message("❌ ต้องเลือกส่วนผสมอย่างน้อย 1 อย่าง", ephemeral=True); return
        if not v.minigame_key:
            await ix.response.send_message("❌ ต้องเลือกมินิเกม", ephemeral=True); return
        cat = load_items_catalog()
        recipe = {"ingredients": ings, "minigame": v.minigame_key}
        if v.existing_id:
            iid = v.existing_id
            if iid not in cat:
                await ix.response.send_message(f"❌ ไอเทม `{iid}` หายไปจาก catalog", ephemeral=True); return
            cat[iid]["type"] = "craft"
            cat[iid]["recipe"] = recipe
            save_items_catalog(cat)
            msg = f"✅ ตั้ง recipe ให้ไอเทมเดิม `{iid}` แล้ว — คราฟได้ทันที"
        else:
            new_id = _slugify(v.basics["name"])
            if new_id in cat:
                new_id = f"{new_id}_{int(time.time())}"
            cat[new_id] = {
                **v.basics,
                "type": "craft",
                "recipe": recipe,
            }
            save_items_catalog(cat)
            iid = new_id
            msg = f"✅ สร้างไอเทมคราฟ `{new_id}` แล้ว — โผล่ใน catalog ทันที"
        await ix.response.edit_message(
            content=msg,
            embed=_build_item_embed(iid, cat[iid]),
            view=None,
        )


class CraftAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ออกแบบ recipe คราฟ", style=discord.ButtonStyle.primary)
    async def btn_design(self, interaction, button):
        await interaction.response.send_message(
            "เลือก **ผลคราฟ** จาก catalog หรือ **สร้างไอเทมใหม่** ↓",
            view=CraftOutputPickerView(),
            ephemeral=True,
        )

    @discord.ui.button(label="ดูคลังไอเทม", style=discord.ButtonStyle.secondary)
    async def btn_list(self, interaction, button):
        await interaction.response.send_message(embed=_items_overview_embed(), view=ItemCatalogView(), ephemeral=True)


@bot.tree.command(name="คราฟแอดมิน", description="[Admin] ออกแบบไอเทมคราฟ", guild=_ORION_GUILD_OBJ)
async def cmd_craft_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    embed = discord.Embed(
        title="Craft — Admin Panel",
        description=(
            "**ออกแบบ recipe คราฟ**\n"
            "1️⃣ เลือก **ผลคราฟ** — ไอเทมเดิมจาก catalog หรือ + สร้างใหม่\n"
            "2️⃣ เลือก **ส่วนผสม** (สูงสุด 3 จาก catalog) + ปรับจำนวน\n"
            "3️⃣ เลือก **มินิเกม** + บันทึก\n\n"
            "_ถ้าเลือกไอเทมเดิม → แค่ผูก recipe เข้าไอเทมนั้น (ไม่สร้างใหม่)_"
        ),
        color=0xe67e22,
    )
    await interaction.response.send_message(embed=embed, view=CraftAdminView(), ephemeral=True)


# ── MINIGAMES ──
async def _mg_guess_number(interaction: discord.Interaction) -> bool:
    target = _orion_random.randint(1, 20)
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    state = {"tries": 5}

    class GuessModal(discord.ui.Modal, title="🎲 ทายเลข 1-20"):
        f_n = discord.ui.TextInput(label="เลขที่ทาย (1-20)", max_length=2)

        async def on_submit(self, ix: discord.Interaction):
            n = _parse_int(self.f_n.value)
            if n is None or not (1 <= n <= 20):
                await ix.response.send_message("ต้องเป็นเลข 1-20", ephemeral=True); return
            if n == target:
                await ix.response.edit_message(content=f"🎉 ถูกแล้ว! เลขคือ **{target}**", view=None)
                if not fut.done(): fut.set_result(True)
                return
            state["tries"] -= 1
            if state["tries"] <= 0:
                await ix.response.edit_message(content=f"💔 หมดสิทธิ์! เลขที่ถูกคือ **{target}**", view=None)
                if not fut.done(): fut.set_result(False)
                return
            hint = "สูงไป ⬇️" if n > target else "ต่ำไป ⬆️"
            await ix.response.edit_message(
                content=f"🎲 **ทายเลข 1-20**\n{n} → {hint} | เหลือ {state['tries']} ครั้ง",
                view=GuessView(),
            )

    class GuessView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="ทาย", style=discord.ButtonStyle.primary)
        async def btn(self, ix, _b):
            await ix.response.send_modal(GuessModal())

        async def on_timeout(self):
            if not fut.done(): fut.set_result(False)

    await interaction.followup.send(
        content=f"🎲 **ทายเลข 1-20** — มี 5 ครั้ง กดปุ่มเพื่อเริ่ม",
        view=GuessView(),
        ephemeral=True,
    )
    try:
        return await asyncio.wait_for(fut, timeout=180)
    except asyncio.TimeoutError:
        return False


async def _mg_math_quick(interaction: discord.Interaction) -> bool:
    a = _orion_random.randint(5, 50)
    b = _orion_random.randint(5, 50)
    op = _orion_random.choice(["+", "-", "×"])
    ans = {"+": a+b, "-": a-b, "×": a*b}[op]
    fut = asyncio.get_event_loop().create_future()

    class MathModal(discord.ui.Modal, title="🧮 คิดเลขเร็ว"):
        f_n = discord.ui.TextInput(label=f"{a} {op} {b} = ?", max_length=8)

        async def on_submit(self, ix: discord.Interaction):
            n = _parse_int(self.f_n.value)
            if n == ans:
                await ix.response.edit_message(content=f"🎉 ถูก! {a} {op} {b} = **{ans}**", view=None)
                if not fut.done(): fut.set_result(True)
            else:
                await ix.response.edit_message(content=f"❌ ผิด! คำตอบที่ถูกคือ **{ans}** (คุณตอบ {self.f_n.value})", view=None)
                if not fut.done(): fut.set_result(False)

    class MathView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="ตอบ", style=discord.ButtonStyle.primary)
        async def btn(self, ix, _b):
            await ix.response.send_modal(MathModal())

        async def on_timeout(self):
            if not fut.done(): fut.set_result(False)

    await interaction.followup.send(content=f"🧮 **คิดเลขเร็ว**\n`{a} {op} {b} = ?`\nกดปุ่มเพื่อตอบ (60 วินาที)", view=MathView(), ephemeral=True)
    try:
        return await asyncio.wait_for(fut, timeout=90)
    except asyncio.TimeoutError:
        return False


async def _mg_click_target(interaction: discord.Interaction) -> bool:
    COLORS = [("🔴", "red"), ("🔵", "blue"), ("🟢", "green"), ("🟡", "yellow"), ("🟣", "purple")]
    fut = asyncio.get_event_loop().create_future()
    state = {"round": 0, "wins": 0, "target_idx": 0, "ordered": []}
    ROUNDS = 3

    def new_round():
        state["round"] += 1
        state["ordered"] = list(range(len(COLORS)))
        _orion_random.shuffle(state["ordered"])
        state["target_idx"] = _orion_random.randint(0, len(COLORS) - 1)

    class ClickView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            for slot, color_idx in enumerate(state["ordered"]):
                emoji, _name = COLORS[color_idx]
                self.add_item(ClickBtn(emoji, color_idx))

        async def on_timeout(self):
            if not fut.done(): fut.set_result(state["wins"] >= ROUNDS - 1)  # ใจดี

    class ClickBtn(discord.ui.Button):
        def __init__(self, emoji_str, color_idx):
            super().__init__(emoji=emoji_str, style=discord.ButtonStyle.secondary)
            self.color_idx = color_idx

        async def callback(self, ix: discord.Interaction):
            if self.color_idx == state["target_idx"]:
                state["wins"] += 1
            if state["round"] >= ROUNDS:
                ok = state["wins"] >= 2
                await ix.response.edit_message(
                    content=f"{'🎉 ผ่าน!' if ok else '💔 แพ้'} — ถูก {state['wins']}/{ROUNDS}",
                    view=None,
                )
                if not fut.done(): fut.set_result(ok)
                return
            new_round()
            target_emoji = COLORS[state["target_idx"]][0]
            await ix.response.edit_message(
                content=f"🎯 **กดปุ่ม {target_emoji} ให้ทัน!** (รอบ {state['round']}/{ROUNDS} · ถูก {state['wins']})",
                view=ClickView(),
            )

    new_round()
    target_emoji = COLORS[state["target_idx"]][0]
    await interaction.followup.send(
        content=f"🎯 **กดปุ่ม {target_emoji} ให้ทัน!** (รอบ {state['round']}/{ROUNDS}) — ต้องถูก 2/3",
        view=ClickView(),
        ephemeral=True,
    )
    try:
        return await asyncio.wait_for(fut, timeout=120)
    except asyncio.TimeoutError:
        return False


_ANAGRAM_WORDS = [
    "sword", "magic", "stone", "river", "dragon", "spell", "shield",
    "crystal", "potion", "metal", "forest", "phoenix", "shadow",
    "thunder", "frost", "ember", "wolf", "tiger", "eagle", "raven",
    "blade", "armor", "scroll", "tome", "rune", "totem",
]


async def _mg_anagram(interaction: discord.Interaction) -> bool:
    word = _orion_random.choice(_ANAGRAM_WORDS).lower()
    letters = list(word)
    _orion_random.shuffle(letters)
    while "".join(letters) == word and len(set(word)) > 1:
        _orion_random.shuffle(letters)
    scrambled = " ".join(letters).upper()
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    class AnagramModal(discord.ui.Modal, title="🔤 จัดเรียงคำ"):
        f_n = discord.ui.TextInput(label=f"เรียง: {scrambled}", placeholder="พิมพ์คำที่ถูกต้อง", max_length=30)

        async def on_submit(self, ix: discord.Interaction):
            answer = (self.f_n.value or "").strip().lower()
            if answer == word:
                await ix.response.edit_message(content=f"🎉 ถูกแล้ว! คำคือ **{word.upper()}**", view=None)
                if not fut.done(): fut.set_result(True)
            else:
                await ix.response.edit_message(
                    content=f"❌ ผิด — คำที่ถูกคือ **{word.upper()}** (คุณตอบ `{self.f_n.value}`)",
                    view=None,
                )
                if not fut.done(): fut.set_result(False)

    class AnagramView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=90)

        @discord.ui.button(label="ตอบ", style=discord.ButtonStyle.primary)
        async def btn(self, ix, _b):
            await ix.response.send_modal(AnagramModal())

        async def on_timeout(self):
            if not fut.done(): fut.set_result(False)

    await interaction.followup.send(
        content=f"🔤 **จัดเรียงคำ** — จับตัวอักษรเรียงให้ถูก (90 วินาที)\n## `{scrambled}`",
        view=AnagramView(),
        ephemeral=True,
    )
    try:
        return await asyncio.wait_for(fut, timeout=120)
    except asyncio.TimeoutError:
        return False


_ODD_EMOJI_PAIRS = [
    ("🍎", "🍌"), ("🐶", "🐱"), ("⚔️", "🛡️"), ("🔴", "🔵"),
    ("⭐", "💫"), ("🌲", "🌴"), ("🪨", "🧊"), ("🌹", "🌻"),
    ("🔥", "💧"), ("🦊", "🦝"),
]


async def _mg_odd_one_out(interaction: discord.Interaction) -> bool:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    state = {"round": 0, "wins": 0, "target_idx": 0, "items": []}
    ROUNDS = 3

    def new_round():
        state["round"] += 1
        same, diff = _orion_random.choice(_ODD_EMOJI_PAIRS)
        items = [same] * 4 + [diff]
        _orion_random.shuffle(items)
        state["items"] = items
        state["target_idx"] = items.index(diff)

    class OddBtn(discord.ui.Button):
        def __init__(self, idx, emoji_str):
            super().__init__(emoji=emoji_str, style=discord.ButtonStyle.secondary)
            self.idx = idx

        async def callback(self, ix: discord.Interaction):
            if self.idx == state["target_idx"]:
                state["wins"] += 1
            if state["round"] >= ROUNDS:
                ok = state["wins"] >= 2
                await ix.response.edit_message(
                    content=f"{'🎉 ผ่าน!' if ok else '💔 แพ้'} — ถูก {state['wins']}/{ROUNDS}",
                    view=None,
                )
                if not fut.done(): fut.set_result(ok)
                return
            new_round()
            await ix.response.edit_message(
                content=f"🔍 **คลิกอันที่ต่างจากเพื่อน!** (รอบ {state['round']}/{ROUNDS} · ถูก {state['wins']})",
                view=OddView(),
            )

    class OddView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30)
            for i, emo in enumerate(state["items"]):
                self.add_item(OddBtn(i, emo))

        async def on_timeout(self):
            if not fut.done():
                fut.set_result(state["wins"] >= 2)

    new_round()
    await interaction.followup.send(
        content=f"🔍 **คลิกอันที่ต่างจากเพื่อน!** (รอบ {state['round']}/{ROUNDS}) — ต้องถูก 2/3",
        view=OddView(),
        ephemeral=True,
    )
    try:
        return await asyncio.wait_for(fut, timeout=120)
    except asyncio.TimeoutError:
        return False


async def _mg_rps(interaction: discord.Interaction) -> bool:
    """เป่ายิ้งฉุบ best of 3 — ชนะ 2 ครั้งผ่าน, แพ้ 2 ครั้งร่วง"""
    state = {"wins": 0, "losses": 0, "ties": 0, "round": 0}
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    LABELS = {"rock": "🪨 ค้อน", "paper": "📄 กระดาษ", "scissors": "✂️ กรรไกร"}
    WIN_PAIRS = {("rock", "scissors"), ("paper", "rock"), ("scissors", "paper")}

    class RPSBtn(discord.ui.Button):
        def __init__(self, choice: str, emoji_str: str):
            super().__init__(emoji=emoji_str, label=LABELS[choice].split(" ", 1)[1], style=discord.ButtonStyle.primary)
            self.choice = choice

        async def callback(self, ix: discord.Interaction):
            bot_pick = _orion_random.choice(["rock", "paper", "scissors"])
            state["round"] += 1
            if self.choice == bot_pick:
                state["ties"] += 1
                result = "🤝 เสมอ"
            elif (self.choice, bot_pick) in WIN_PAIRS:
                state["wins"] += 1
                result = "✅ ชนะ"
            else:
                state["losses"] += 1
                result = "❌ แพ้"
            line = (
                f"คุณออก: {LABELS[self.choice]}  vs  บอท: {LABELS[bot_pick]}\n"
                f"{result} | สกอร์ — ชนะ {state['wins']} · แพ้ {state['losses']} · เสมอ {state['ties']}"
            )
            if state["wins"] >= 2:
                await ix.response.edit_message(content=f"🎉 **ผ่าน!**\n{line}", view=None)
                if not fut.done(): fut.set_result(True); return
            if state["losses"] >= 2:
                await ix.response.edit_message(content=f"💔 **แพ้**\n{line}", view=None)
                if not fut.done(): fut.set_result(False); return
            await ix.response.edit_message(
                content=f"✊ **เป่ายิ้งฉุบ — best of 3**\n{line}\nเลือกอีกครั้ง ↓",
                view=RPSView(),
            )

    class RPSView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            self.add_item(RPSBtn("rock", "🪨"))
            self.add_item(RPSBtn("paper", "📄"))
            self.add_item(RPSBtn("scissors", "✂️"))

        async def on_timeout(self):
            if not fut.done(): fut.set_result(state["wins"] > state["losses"])

    await interaction.followup.send(
        content="✊ **เป่ายิ้งฉุบ — best of 3** — ชนะให้ได้ 2 ครั้งก่อนแพ้ 2 ครั้ง",
        view=RPSView(),
        ephemeral=True,
    )
    try:
        return await asyncio.wait_for(fut, timeout=120)
    except asyncio.TimeoutError:
        return False


async def _mg_number_sort(interaction: discord.Interaction) -> bool:
    """กดเลข 4 ตัวจากน้อยไปมาก — กดผิด 1 ครั้งคือแพ้"""
    nums = sorted(_orion_random.sample(range(1, 100), 4))
    shuffled = list(nums)
    while shuffled == nums:
        _orion_random.shuffle(shuffled)
    state = {"expected": list(nums), "step": 0}
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    class SortBtn(discord.ui.Button):
        def __init__(self, n: int):
            super().__init__(label=str(n), style=discord.ButtonStyle.secondary)
            self.n = n

        async def callback(self, ix: discord.Interaction):
            if self.disabled:
                await ix.response.defer(); return
            expected_next = state["expected"][state["step"]]
            if self.n != expected_next:
                await ix.response.edit_message(
                    content=f"❌ ผิด! ที่ถูกคือ **{expected_next}** ก่อน — ลำดับที่ถูก: `{' < '.join(map(str, nums))}`",
                    view=None,
                )
                if not fut.done(): fut.set_result(False); return
            state["step"] += 1
            self.style = discord.ButtonStyle.success
            self.disabled = True
            self.label = f"{self.n} ✓"
            if state["step"] >= len(nums):
                await ix.response.edit_message(
                    content=f"🎉 **ผ่าน!** เรียงถูกหมด: `{' < '.join(map(str, nums))}`",
                    view=None,
                )
                if not fut.done(): fut.set_result(True); return
            await ix.response.edit_message(
                content=f"🔢 **เรียงน้อย → มาก** — ต่อไป ({state['step']+1}/4)",
                view=self.view,
            )

    class SortView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)
            for n in shuffled:
                self.add_item(SortBtn(n))

        async def on_timeout(self):
            if not fut.done(): fut.set_result(False)

    await interaction.followup.send(
        content=f"🔢 **เรียงตัวเลขจากน้อยไปมาก** — กดทีละปุ่มตามลำดับ (60 วินาที)",
        view=SortView(),
        ephemeral=True,
    )
    try:
        return await asyncio.wait_for(fut, timeout=90)
    except asyncio.TimeoutError:
        return False


_EMOJI_COUNT_SET = ["🍎", "🍊", "🍇", "🍓", "🍌"]


async def _mg_emoji_count(interaction: discord.Interaction) -> bool:
    """นับ emoji ที่ระบุในแถว 15 ตัว"""
    target = _orion_random.choice(_EMOJI_COUNT_SET)
    line = [_orion_random.choice(_EMOJI_COUNT_SET) for _ in range(15)]
    # บังคับให้ target โผล่อย่างน้อย 3 ตัว เพื่อกัน 0
    while line.count(target) < 3:
        line[_orion_random.randint(0, 14)] = target
    correct = line.count(target)
    line_str = "".join(line)
    fut: asyncio.Future = asyncio.get_event_loop().create_future()

    class CountModal(discord.ui.Modal, title="🔎 นับ emoji"):
        f_n = discord.ui.TextInput(label=f"นับ {target} มีกี่ตัว?", max_length=3)

        async def on_submit(self, ix: discord.Interaction):
            n = _parse_int(self.f_n.value, -1)
            if n == correct:
                await ix.response.edit_message(content=f"🎉 ถูก! มี **{correct}** ตัว", view=None)
                if not fut.done(): fut.set_result(True)
            else:
                await ix.response.edit_message(
                    content=f"❌ ผิด — มีจริง **{correct}** ตัว (คุณตอบ {self.f_n.value})",
                    view=None,
                )
                if not fut.done(): fut.set_result(False)

    class CountView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=60)

        @discord.ui.button(label="ตอบ", style=discord.ButtonStyle.primary)
        async def btn(self, ix, _b):
            await ix.response.send_modal(CountModal())

        async def on_timeout(self):
            if not fut.done(): fut.set_result(False)

    await interaction.followup.send(
        content=(
            f"🔎 **นับ emoji {target} ในแถวนี้** (60 วินาที)\n\n"
            f"## {line_str}"
        ),
        view=CountView(),
        ephemeral=True,
    )
    try:
        return await asyncio.wait_for(fut, timeout=90)
    except asyncio.TimeoutError:
        return False


async def _run_minigame(interaction: discord.Interaction, minigame: str) -> bool:
    if minigame == "guess_number": return await _mg_guess_number(interaction)
    if minigame == "math_quick":   return await _mg_math_quick(interaction)
    if minigame == "click_target": return await _mg_click_target(interaction)
    if minigame == "anagram":      return await _mg_anagram(interaction)
    if minigame == "odd_one_out":  return await _mg_odd_one_out(interaction)
    if minigame == "rps":          return await _mg_rps(interaction)
    if minigame == "number_sort":  return await _mg_number_sort(interaction)
    if minigame == "emoji_count":  return await _mg_emoji_count(interaction)
    return True   # ถ้า recipe ไม่มี minigame = ผ่านอัตโนมัติ


# ── CRAFT (player side) ──
class CraftRecipeSelect(discord.ui.Select):
    def __init__(self, uid: str, page: int = 0):
        self.uid = uid
        self.page = page
        cat = load_items_catalog()
        crafts = sorted(
            [(iid, it) for iid, it in cat.items() if it.get("type") == "craft"],
            key=lambda x: x[1].get("name", x[0]).lower(),
        )
        total = len(crafts)
        page_size = 23
        max_page = max(0, (total - 1) // page_size)
        start = page * page_size
        end = start + page_size
        page_items = crafts[start:end]
        options = []
        for iid, it in page_items:
            options.append(discord.SelectOption(
                label=it.get("name", "?")[:100],
                value=iid,
                description=(it.get("description", "")[:80] or "—"),
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if page < max_page:
            options.append(discord.SelectOption(
                label="→ หน้าถัดไป",
                value=f"__nextpage__:{page+1}",
                description=f"ดูหน้า {page+2}/{max_page+1}",
            ))
        if page > 0:
            options.append(discord.SelectOption(
                label="← หน้าก่อน",
                value=f"__nextpage__:{page-1}",
                description=f"กลับหน้า {page}/{max_page+1}",
            ))
        if not options:
            options = [discord.SelectOption(label="ยังไม่มี recipe", value="none")]
        ph_suffix = f" (หน้า {page+1}/{max_page+1})" if max_page > 0 else ""
        super().__init__(placeholder=f"เลือก recipe ที่อยากคราฟ{ph_suffix}...", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        # pagination
        if self.values[0].startswith("__nextpage__:"):
            new_page = int(self.values[0].split(":", 1)[1])
            new_view = CraftMenuView(self.uid, page=new_page)
            await interaction.response.edit_message(view=new_view)
            return
        iid = self.values[0]
        item = get_item(iid)
        view = CraftConfirmView(self.uid, iid)
        embed = _build_item_embed(iid, item)
        # เช็คว่ามีของพอ
        ings = item.get("recipe", {}).get("ingredients", [])
        has = player_has_items(self.uid, ings)
        embed.add_field(
            name="✅ ของในกระเป๋า",
            value="พอที่จะคราฟ ✅" if has else "**ของไม่พอ ❌**",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class CraftConfirmView(discord.ui.View):
    def __init__(self, uid: str, iid: str):
        super().__init__(timeout=180)
        self.uid = uid
        self.iid = iid

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.uid:
            await interaction.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return False
        return True

    @discord.ui.button(label="เริ่มคราฟ", style=discord.ButtonStyle.success)
    async def btn_start(self, interaction: discord.Interaction, button):
        item = get_item(self.iid)
        ings = item.get("recipe", {}).get("ingredients", [])
        if not player_has_items(self.uid, ings):
            await interaction.response.send_message("❌ ของในกระเป๋าไม่พอที่จะคราฟ", ephemeral=True); return
        await interaction.response.defer(ephemeral=True)
        minigame = item.get("recipe", {}).get("minigame", "")
        result = await _run_minigame(interaction, minigame)
        if result:
            # consume ingredients + add output
            for ing in ings:
                remove_player_item(self.uid, ing["item_id"], ing["qty"])
            add_player_item(self.uid, self.iid, 1)
            await interaction.followup.send(
                f"🎉 คราฟสำเร็จ! ได้รับ {item.get('emoji','📦')} **{item.get('name','?')}** ×1",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"💔 คราฟล้มเหลว — ส่วนผสมไม่เสีย ลองใหม่ได้",
                ephemeral=True,
            )


class CraftMenuView(discord.ui.View):
    def __init__(self, uid: str, page: int = 0):
        super().__init__(timeout=300)
        self.add_item(CraftRecipeSelect(uid, page=page))


@bot.tree.command(name="คราฟ", description="คราฟไอเทม (มีมินิเกม)", guild=_ORION_GUILD_OBJ)
async def cmd_craft(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    cat = load_items_catalog()
    crafts = [(iid, it) for iid, it in cat.items() if it.get("type") == "craft"]
    embed = discord.Embed(
        title="🛠️  คราฟไอเทม",
        description=(
            f"เลือก recipe ที่อยากคราฟจาก dropdown ด้านล่าง\n"
            f"**Recipe ทั้งหมด:** {len(crafts)} อัน\n"
            "_ของในกระเป๋าจะเสียก็ต่อเมื่อคราฟสำเร็จเท่านั้น_"
        ),
        color=0xe67e22,
    )
    await interaction.response.send_message(embed=embed, view=CraftMenuView(uid), ephemeral=_eph("คราฟ"))


# ████████████████████████████████████████████████████████████
# ████  GUILD SYSTEM  ████████████████████████████████████████
# ████████████████████████████████████████████████████████████

def load_guilds() -> dict:
    return load_json(GUILDS_FILE, {})


def save_guilds(d: dict):
    save_json(GUILDS_FILE, d)


def get_player_guild(uid: str):
    """return (gid, guild_dict) หรือ None"""
    guilds = load_guilds()
    for gid, g in guilds.items():
        for m in g.get("members", []):
            if m.get("uid") == uid:
                return gid, g
    return None


def member_rank(g: dict, uid: str) -> str:
    for m in g.get("members", []):
        if m.get("uid") == uid:
            return m.get("rank", "member")
    return ""


RANK_LABEL = {"owner": "👑 หัวกิลด์", "officer": "⚔️ ขุนพล", "member": "🛡️ สมาชิก"}
RANK_ORDER = {"owner": 0, "officer": 1, "member": 2}


def _guild_embed(gid: str, g: dict) -> discord.Embed:
    cfg = load_currency_cfg()
    embed = discord.Embed(
        title=f"Guild · {g.get('name','?')}",
        description=g.get("description") or "_— ไม่มีคำอธิบาย —_",
        color=0x9b59b6,
    )
    if g.get("image_url"):
        embed.set_thumbnail(url=g["image_url"])
    members = sorted(g.get("members", []), key=lambda m: RANK_ORDER.get(m.get("rank","member"), 9))
    lines = [f"{RANK_LABEL.get(m.get('rank','member'),'')} <@{m['uid']}>" for m in members]
    embed.add_field(name=f"สมาชิก `{len(members)}/{g.get('slots',5)}`",
                    value="\n".join(lines) or "_ว่าง_", inline=False)
    embed.add_field(name="สร้างเมื่อ", value=g.get("created_at","—"), inline=True)
    embed.add_field(name="ค่า slot",   value=f"{cfg['emoji']} `{cfg['guild_slot_cost']:,}`", inline=True)
    embed.set_footer(text=f"ID: {gid}")
    return embed


class GuildCreateModal(discord.ui.Modal, title="🏰 สร้างกิลด์ใหม่"):
    f_name  = discord.ui.TextInput(label="ชื่อกิลด์", max_length=50)
    f_desc  = discord.ui.TextInput(label="คำขวัญ / คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)
    f_image = discord.ui.TextInput(label="URL รูปกิลด์ (ไม่บังคับ)", required=False, max_length=400)

    async def on_submit(self, interaction: discord.Interaction):
        uid = str(interaction.user.id)
        if get_player_guild(uid) is not None:
            await interaction.response.send_message("❌ คุณอยู่ในกิลด์อยู่แล้ว ออกก่อนค่อยสร้างใหม่", ephemeral=True); return
        # เช็คเงิน (ถ้าตั้งราคา > 0)
        cfg = load_currency_cfg()
        cost = int(cfg.get("guild_create_cost", 0))
        if cost > 0:
            if get_wallet(uid) < cost:
                await interaction.response.send_message(
                    f"❌ เงินไม่พอ! สร้างกิลด์ต้องใช้ {money_str(cost)} (มี {money_str(get_wallet(uid))})",
                    ephemeral=True,
                )
                return
            add_money(uid, -cost)
        # สร้างกิลด์
        gid = _orion_uuid.uuid4().hex[:8]
        guilds = load_guilds()
        guilds[gid] = {
            "name":        self.f_name.value.strip(),
            "description": (self.f_desc.value or "").strip(),
            "image_url":   (self.f_image.value or "").strip(),
            "owner_id":    uid,
            "members":     [{"uid": uid, "rank": "owner"}],
            "slots":       5,
            "created_at":  datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "invites":     [],
        }
        save_guilds(guilds)
        # set guild_id ในโปรไฟล์ผู้เล่น
        ensure_orion_player(uid)
        pdata = load_orion_players()
        pdata[uid]["guild_id"] = gid
        save_orion_players(pdata)
        msg = f"✅ สร้างกิลด์ **{guilds[gid]['name']}** สำเร็จ!"
        if cost > 0:
            msg += f" หัก {money_str(cost)}"
        await interaction.response.send_message(
            msg,
            embed=_guild_embed(gid, guilds[gid]),
            view=GuildPanelView(gid, uid),
            ephemeral=True,
        )


def _do_guild_invite(gid: str, target_uid: str) -> str:
    guilds = load_guilds()
    g = guilds.get(gid)
    if not g:
        return "❌ ไม่พบกิลด์"
    if get_player_guild(target_uid) is not None:
        return "❌ คนนี้อยู่กิลด์อื่นอยู่แล้ว"
    if len(g.get("members", [])) >= g.get("slots", 5):
        return f"❌ กิลด์เต็ม ({g.get('slots',5)} slots) — เพิ่ม slot ก่อน"
    g.setdefault("invites", [])
    if target_uid in g["invites"]:
        return "⚠️ ส่งคำเชิญไปแล้ว"
    g["invites"].append(target_uid)
    save_guilds(guilds)
    return f"✅ ส่งคำเชิญถึง <@{target_uid}> — บอกให้เขาใช้ `/guild` เพื่อกดรับ"


class GuildInviteUserSelect(discord.ui.UserSelect):
    def __init__(self, gid: str):
        super().__init__(placeholder="📨 เลือกคนที่จะเชิญ...", min_values=1, max_values=1)
        self.gid = gid

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ ชวนบอทไม่ได้", ephemeral=True); return
        result = _do_guild_invite(self.gid, str(target.id))
        # DM
        try:
            g = load_guilds().get(self.gid, {})
            await target.send(
                f"📨 คุณได้รับคำเชิญเข้าร่วมกิลด์ **{g.get('name','?')}**!\n"
                f"ใช้ `/guild` ในเซิร์ฟ Orion → กดปุ่ม **เข้าร่วมกิลด์** เพื่อรับคำเชิญ"
            )
        except Exception:
            pass
        await ix.response.send_message(result, ephemeral=True)


class GuildInviteView(discord.ui.View):
    def __init__(self, gid: str):
        super().__init__(timeout=180)
        self.add_item(GuildInviteUserSelect(gid))


class GuildMemberSelect(discord.ui.Select):
    """Dropdown สมาชิกของกิลด์ (ยกเว้น owner)"""
    def __init__(self, gid: str, placeholder: str, *, action: str):
        self.gid = gid
        self.action = action
        guilds = load_guilds()
        g = guilds.get(gid, {})
        options = []
        for m in g.get("members", []):
            if m.get("rank") == "owner":
                continue
            uid = m["uid"]
            user = bot.get_user(int(uid)) if uid.isdigit() else None
            name = user.display_name if user else f"User {uid}"
            options.append(discord.SelectOption(
                label=name[:100],
                value=uid,
                description=f"ตอนนี้: {RANK_LABEL.get(m.get('rank','member'),'')}"[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีสมาชิกอื่น", value="none")]
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1)

    async def callback(self, ix: discord.Interaction):
        uid = self.values[0]
        if uid == "none":
            await ix.response.defer(); return
        guilds = load_guilds()
        g = guilds.get(self.gid)
        if not g:
            await ix.response.send_message("❌ ไม่พบกิลด์", ephemeral=True); return
        m = next((x for x in g.get("members", []) if x["uid"] == uid), None)
        if not m:
            await ix.response.send_message("❌ ไม่ใช่สมาชิก", ephemeral=True); return
        if self.action == "promote":
            await ix.response.send_message(
                f"⚔️ เลือกตำแหน่งใหม่สำหรับ <@{uid}> ↓",
                view=GuildRankPickerView(self.gid, uid),
                ephemeral=True,
            )
        elif self.action == "kick":
            g["members"].remove(m)
            save_guilds(guilds)
            pdata = load_orion_players()
            if uid in pdata:
                pdata[uid]["guild_id"] = ""
                save_orion_players(pdata)
            await ix.response.edit_message(content=f"🚪 เตะ <@{uid}> ออกจากกิลด์แล้ว", view=None)


class GuildPromoteView(discord.ui.View):
    def __init__(self, gid: str):
        super().__init__(timeout=180)
        self.add_item(GuildMemberSelect(gid, "⚔️ เลือกสมาชิกที่จะแต่งตั้ง/ปลด...", action="promote"))


class GuildKickView(discord.ui.View):
    def __init__(self, gid: str):
        super().__init__(timeout=180)
        self.add_item(GuildMemberSelect(gid, "🚪 เลือกสมาชิกที่จะเตะ...", action="kick"))


class GuildRankPickerView(discord.ui.View):
    def __init__(self, gid: str, target_uid: str):
        super().__init__(timeout=120)
        self.gid = gid
        self.target_uid = target_uid

    async def _set_rank(self, ix: discord.Interaction, rank: str):
        guilds = load_guilds()
        g = guilds.get(self.gid)
        if not g:
            await ix.response.send_message("❌ ไม่พบกิลด์", ephemeral=True); return
        m = next((x for x in g.get("members", []) if x["uid"] == self.target_uid), None)
        if not m:
            await ix.response.send_message("❌ ไม่ใช่สมาชิก", ephemeral=True); return
        if m.get("rank") == "owner":
            await ix.response.send_message("❌ เปลี่ยนตำแหน่งหัวกิลด์ไม่ได้", ephemeral=True); return
        m["rank"] = rank
        save_guilds(guilds)
        await ix.response.edit_message(content=f"✅ ตั้ง <@{self.target_uid}> เป็น **{RANK_LABEL.get(rank)}**", view=None)

    @discord.ui.button(label="ขุนพล", style=discord.ButtonStyle.primary)
    async def btn_officer(self, ix, _b): await self._set_rank(ix, "officer")

    @discord.ui.button(label="สมาชิก", style=discord.ButtonStyle.secondary)
    async def btn_member(self, ix, _b): await self._set_rank(ix, "member")


class GuildPanelView(discord.ui.View):
    def __init__(self, gid: str, viewer_uid: str):
        super().__init__(timeout=300)
        self.gid = gid
        self.viewer_uid = viewer_uid
        guilds = load_guilds()
        g = guilds.get(gid, {})
        my_rank = member_rank(g, viewer_uid)
        is_owner = my_rank == "owner"
        is_officer = my_rank in ("owner", "officer")

        if not is_officer:
            # member: เห็นแค่ปุ่มออก
            self.add_item(LeaveGuildBtn(gid, viewer_uid))
            return

        self.add_item(InviteBtn(gid))
        self.add_item(BuySlotBtn(gid))
        if is_owner:
            self.add_item(PromoteBtn(gid))
            self.add_item(KickBtn(gid))
            self.add_item(DisbandBtn(gid))
        self.add_item(LeaveGuildBtn(gid, viewer_uid))


class InviteBtn(discord.ui.Button):
    def __init__(self, gid):
        super().__init__(label="เชิญสมาชิก", style=discord.ButtonStyle.success, row=0)
        self.gid = gid
    async def callback(self, ix: discord.Interaction):
        await ix.response.send_message(
            "📨 เลือกผู้เล่นที่จะเชิญจาก dropdown ↓",
            view=GuildInviteView(self.gid),
            ephemeral=True,
        )


class BuySlotBtn(discord.ui.Button):
    def __init__(self, gid):
        super().__init__(label="ซื้อ Slot (+1)", style=discord.ButtonStyle.primary, row=0)
        self.gid = gid
    async def callback(self, ix: discord.Interaction):
        guilds = load_guilds()
        g = guilds.get(self.gid)
        if not g:
            await ix.response.send_message("❌ ไม่พบกิลด์", ephemeral=True); return
        cfg = load_currency_cfg()
        cost = int(cfg.get("guild_slot_cost", 0))
        uid = str(ix.user.id)
        if cost > 0:
            if get_wallet(uid) < cost:
                await ix.response.send_message(
                    f"❌ เงินไม่พอ! ต้องใช้ {money_str(cost)} (มี {money_str(get_wallet(uid))})",
                    ephemeral=True,
                ); return
            add_money(uid, -cost)
        g["slots"] = g.get("slots", 5) + 1
        save_guilds(guilds)
        suffix = f"(หัก {money_str(cost)})" if cost > 0 else "(ฟรี)"
        await ix.response.send_message(f"✅ เพิ่ม slot เป็น {g['slots']} แล้ว {suffix}", ephemeral=True)


class PromoteBtn(discord.ui.Button):
    def __init__(self, gid):
        super().__init__(label="แต่งตั้ง/ปลด", style=discord.ButtonStyle.secondary, row=1)
        self.gid = gid
    async def callback(self, ix: discord.Interaction):
        await ix.response.send_message(
            "⚔️ เลือกสมาชิกจาก dropdown ↓",
            view=GuildPromoteView(self.gid),
            ephemeral=True,
        )


class KickBtn(discord.ui.Button):
    def __init__(self, gid):
        super().__init__(label="เตะสมาชิก", style=discord.ButtonStyle.secondary, row=1)
        self.gid = gid
    async def callback(self, ix: discord.Interaction):
        await ix.response.send_message(
            "🚪 เลือกสมาชิกที่จะเตะจาก dropdown ↓",
            view=GuildKickView(self.gid),
            ephemeral=True,
        )


class DisbandBtn(discord.ui.Button):
    def __init__(self, gid):
        super().__init__(label="ยุบกิลด์", style=discord.ButtonStyle.danger, row=2)
        self.gid = gid
    async def callback(self, ix: discord.Interaction):
        view = DisbandConfirmView(self.gid)
        await ix.response.send_message("⚠️ **ยุบกิลด์ถาวร?** การกระทำนี้ย้อนกลับไม่ได้", view=view, ephemeral=True)


class DisbandConfirmView(discord.ui.View):
    def __init__(self, gid):
        super().__init__(timeout=60)
        self.gid = gid

    @discord.ui.button(label="ยืนยันยุบ", style=discord.ButtonStyle.danger)
    async def btn_yes(self, ix: discord.Interaction, _b):
        guilds = load_guilds()
        g = guilds.pop(self.gid, None)
        if not g:
            await ix.response.edit_message(content="❌ ไม่พบกิลด์", view=None); return
        save_guilds(guilds)
        # clear guild_id ของสมาชิกทั้งหมด
        pdata = load_orion_players()
        for m in g.get("members", []):
            if m["uid"] in pdata:
                pdata[m["uid"]]["guild_id"] = ""
        save_orion_players(pdata)
        await ix.response.edit_message(content=f"💥 ยุบกิลด์ **{g.get('name')}** เรียบร้อย", view=None)

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def btn_no(self, ix: discord.Interaction, _b):
        await ix.response.edit_message(content="❌ ยกเลิกการยุบ", view=None)


class LeaveGuildBtn(discord.ui.Button):
    def __init__(self, gid, uid):
        super().__init__(label="ออกจากกิลด์", emoji="👋", style=discord.ButtonStyle.danger, row=2)
        self.gid = gid
        self.uid = uid
    async def callback(self, ix: discord.Interaction):
        guilds = load_guilds()
        g = guilds.get(self.gid)
        if not g:
            await ix.response.send_message("❌ ไม่พบกิลด์", ephemeral=True); return
        m = next((x for x in g.get("members", []) if x["uid"] == self.uid), None)
        if not m:
            await ix.response.send_message("❌ ไม่ใช่สมาชิก", ephemeral=True); return
        if m.get("rank") == "owner":
            await ix.response.send_message("❌ หัวกิลด์ออกเองไม่ได้ — ใช้ปุ่ม **ยุบกิลด์** หรือโอนตำแหน่งก่อน", ephemeral=True); return
        g["members"].remove(m)
        save_guilds(guilds)
        pdata = load_orion_players()
        if self.uid in pdata:
            pdata[self.uid]["guild_id"] = ""
            save_orion_players(pdata)
        await ix.response.send_message(f"👋 ออกจากกิลด์ **{g.get('name')}** แล้ว", ephemeral=True)


class GuildEntryView(discord.ui.View):
    """View หลักของ /guild เมื่อยังไม่อยู่กิลด์ไหน"""
    def __init__(self, uid: str):
        super().__init__(timeout=180)
        self.uid = uid
        # เช็คคำเชิญที่ค้างอยู่
        guilds = load_guilds()
        invites = [(gid, g) for gid, g in guilds.items() if uid in g.get("invites", [])]
        if invites:
            self.add_item(AcceptInviteSelect(uid, invites))

    @discord.ui.button(label="สร้างกิลด์ใหม่", style=discord.ButtonStyle.success)
    async def btn_create(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(GuildCreateModal())


class AcceptInviteSelect(discord.ui.Select):
    def __init__(self, uid: str, invites: list):
        self.uid = uid
        options = []
        for gid, g in invites[:25]:
            options.append(discord.SelectOption(
                label=g.get("name", "?")[:100],
                value=gid,
                description=f"สมาชิก {len(g.get('members',[]))}/{g.get('slots',5)}",
            ))
        super().__init__(placeholder="📨 รับคำเชิญที่ค้างอยู่...", options=options)

    async def callback(self, ix: discord.Interaction):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True); return
        gid = self.values[0]
        guilds = load_guilds()
        g = guilds.get(gid)
        if not g or self.uid not in g.get("invites", []):
            await ix.response.send_message("❌ คำเชิญหมดอายุ", ephemeral=True); return
        if len(g.get("members", [])) >= g.get("slots", 5):
            await ix.response.send_message("❌ กิลด์เต็มแล้ว", ephemeral=True); return
        if get_player_guild(self.uid) is not None:
            await ix.response.send_message("❌ คุณอยู่กิลด์อื่นแล้ว", ephemeral=True); return
        g["invites"].remove(self.uid)
        g.setdefault("members", []).append({"uid": self.uid, "rank": "member"})
        save_guilds(guilds)
        pdata = load_orion_players()
        ensure_orion_player(self.uid)
        pdata = load_orion_players()
        pdata[self.uid]["guild_id"] = gid
        save_orion_players(pdata)
        await ix.response.send_message(
            f"✅ เข้าร่วมกิลด์ **{g['name']}** สำเร็จ!",
            embed=_guild_embed(gid, g),
            view=GuildPanelView(gid, self.uid),
            ephemeral=True,
        )


@bot.tree.command(name="guild", description="ระบบกิลด์ — สร้าง/ดู/จัดการ", guild=_ORION_GUILD_OBJ)
async def cmd_guild(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    info = get_player_guild(uid)
    cfg = load_currency_cfg()
    eph = _eph("guild")
    if info:
        gid, g = info
        await interaction.response.send_message(
            embed=_guild_embed(gid, g),
            view=GuildPanelView(gid, uid),
            ephemeral=eph,
        )
    else:
        guilds = load_guilds()
        invites = [g for gid, g in guilds.items() if uid in g.get("invites", [])]
        c_cost = int(cfg.get("guild_create_cost", 0))
        s_cost = int(cfg.get("guild_slot_cost", 0))
        create_text = money_str(c_cost) if c_cost > 0 else "ฟรี"
        slot_text   = money_str(s_cost) if s_cost > 0 else "ฟรี"
        embed = discord.Embed(
            title="Guild — Main Menu",
            description=(
                f"_คุณยังไม่อยู่ในกิลด์ใด_\n\n"
                f"**ค่าสร้างกิลด์**\n{create_text}\n\n"
                f"**ค่าเพิ่ม slot**\n{slot_text}\n\n"
                f"**เงินของคุณ**\n{money_str(get_wallet(uid))}\n\n"
                f"**คำเชิญที่ค้าง**\n`{len(invites)}` รายการ"
            ),
            color=0x9b59b6,
        )
        await interaction.response.send_message(embed=embed, view=GuildEntryView(uid), ephemeral=eph)


# ████████████████████████████████████████████████████████████
# ████  TRAINING + SCAVENGE + FAMILIA + AUCTION  ████████████
# ████████████████████████████████████████████████████████████
import orion_training   # register /ฝึกสกิล /ฝึกแอดมิน
import orion_scavenge   # register /หาของ /หาของแอดมิน /หาของห้อง
import orion_job        # register /งาน /งาน-เจ้าของ /งาน-แอดมิน + passive loop
import orion_familia    # register /familia /familiaแอดมิน + passive loop
import orion_auction    # register /ลงประมูล /ประมูล /ปิดประมูล /ดูประมูล /ประมูลแอดมิน
import orion_shop       # register /ร้าน /ร้านแอดมิน /ร้านอัปโหลด /คูปอง
import orion_roles      # register /บทบาท /บทบาทแอดมิน
import orion_casino     # register /คาสิโน /คาสิโนห้อง
import orion_gacha      # register /กาชา /กาชาแอดมิน /กาชาดาวน์โหลด /กาชาอัปโหลด
import orion_skill_toggle  # register /สกิลใช้ /สกิลตั้งCD /สกิลตั้งCDผู้เล่น
import orion_territory  # register /พื้นที่ /สงคราม /สงครามรางวัล /พื้นที่แอดมิน
import orion_stats      # register /ฝึกสถิติ /ฝึกสถิติแอดมิน
import orion_creation   # register /สร้าง /สร้างแอดมิน
import orion_missions   # register /ภารกิจ /ภารกิจแอดมิน
import orion_config     # register /config (Orion)
import orion_logs       # register /logsแอดมิน /logtest + log_action

# ── AoT integration (Guild2 only — Attack on Titan) ──
import aot_bot_instance   # alias to our bot
import aot_profile        # register /profile (Guild2)
import aot_admin          # register /admin (Guild2)
import aot_items          # register /item-admin + /items (Guild2)
import aot_shifter        # register /shifter group + background tasks (filtered to Guild2)
import aot_set            # register /set profile, /set banner (Guild2)
import aot_config         # register /config (Guild2)
import aot_announcement   # register /paradis-announcement (Guild2)
import aot_shop           # register /shop-setup, /shop-config, /shop + restock task (Guild2)
import aot_economy        # register /balance (Guild2)
import aot_logs           # register /logs-setup (Guild2)
import aot_mission        # register /mission group (Guild2)
import aot_job            # register /job, /job-owner, /job-admin + passive-income task (Guild2)
import aot_xp             # register /xp (Guild2)
import aot_squad          # register /squad (Guild2)
import aot_mindless       # register /mindless, /mindless-inject (Guild2)
import aot_backup         # register /backup (Guild2)


# ████████████████████████████████████████████████████████████
# ████  /setting — admin toggle ephemeral per command  ██████
# ████████████████████████████████████████████████████████████

class SettingToggleSelect(discord.ui.Select):
    def __init__(self):
        cfg = load_settings()
        public = set(cfg.get("public_commands", []))
        options = []
        for cmd_name, desc in TOGGLEABLE_COMMANDS:
            is_public = cmd_name in public
            options.append(discord.SelectOption(
                label=f"{'🌐' if is_public else '🔒'} /{cmd_name}",
                value=cmd_name,
                description=f"{'PUBLIC' if is_public else 'PRIVATE'} — {desc}"[:80],
                default=is_public,
            ))
        super().__init__(
            placeholder="✅ ติ๊กที่ต้องการให้ public (เห็นทุกคน)...",
            options=options,
            min_values=0,
            max_values=len(options),
        )

    async def callback(self, ix: discord.Interaction):
        cfg = load_settings()
        cfg["public_commands"] = list(self.values)
        save_settings(cfg)
        # rebuild embed
        embed = _build_setting_embed()
        view = SettingView()
        await ix.response.edit_message(embed=embed, view=view)


class SettingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(SettingToggleSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True


def _build_setting_embed() -> discord.Embed:
    cfg = load_settings()
    public = set(cfg.get("public_commands", []))
    lines = []
    for cmd_name, desc in TOGGLEABLE_COMMANDS:
        icon = "🌐 PUBLIC" if cmd_name in public else "🔒 PRIVATE"
        lines.append(f"{icon} · `/{cmd_name}` — {desc}")
    return discord.Embed(
        title="⚙️  Setting — ความเป็นส่วนตัวของคำสั่ง",
        description=(
            "**🌐 PUBLIC** = ทุกคนในห้องเห็นผลลัพธ์\n"
            "**🔒 PRIVATE** = เห็นเฉพาะคนที่ใช้คำสั่ง (default)\n\n"
            "เลือกจาก dropdown ด้านล่าง — เครื่องหมายติ๊ก = public\n\n"
            + "\n".join(lines)
        ),
        color=0x95a5a6,
    )


# ── /ตั้งคำสั่ง — เปิด/ปิด commands ต่อ guild ──
_TOGGLEABLE_ALL_CMDS = [c[0] for c in TOGGLEABLE_COMMANDS] + [
    "orionแอดมิน","ไอเทมแอดมิน","เงินแอดมิน","คราฟแอดมิน","ฝึกแอดมิน","หาของแอดมิน",
    "หาของห้อง","ร้านแอดมิน","ร้านอัปโหลด","ประมูลแอดมิน","familiaแอดมิน",
    "บทบาทแอดมิน","คาสิโนแอดมิน","กาชาแอดมิน","กาชาดาวน์โหลด","กาชาอัปโหลด",
    "พื้นที่แอดมิน","สงคราม","สงครามรางวัล","คำขอสกิล","ไอเทมดาวน์โหลด","ไอเทมอัปโหลด",
]
# unique cap 25
_seen = set(); _TOGGLEABLE_ALL_CMDS = [c for c in _TOGGLEABLE_ALL_CMDS if not (c in _seen or _seen.add(c))][:25]


class EnabledCmdToggleSelect(discord.ui.Select):
    def __init__(self):
        cfg = load_settings()
        enabled_list = cfg.get("enabled_commands", None)
        options = []
        for cmd in _TOGGLEABLE_ALL_CMDS:
            on = (enabled_list is None) or (cmd in enabled_list)
            options.append(discord.SelectOption(
                label=f"/{cmd}"[:100],
                value=cmd,
                default=on,
            ))
        super().__init__(
            placeholder="ติ๊กคำสั่งที่ต้องการให้เปิด",
            options=options, min_values=0, max_values=len(options),
        )

    async def callback(self, ix):
        cfg = load_settings()
        cfg["enabled_commands"] = list(self.values)
        save_settings(cfg)
        await ix.response.send_message(
            f"✅ เปิด {len(self.values)} คำสั่งในเซิร์ฟนี้",
            ephemeral=True,
        )


class EnableAllBtn(discord.ui.Button):
    def __init__(self):
        super().__init__(label="เปิดทุกคำสั่ง (default)", style=discord.ButtonStyle.success, row=1)
    async def callback(self, ix):
        cfg = load_settings()
        cfg.pop("enabled_commands", None)
        save_settings(cfg)
        await ix.response.send_message("✅ เปิดทุกคำสั่งแล้ว (default)", ephemeral=True)


class EnabledCmdView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(EnabledCmdToggleSelect())
        self.add_item(EnableAllBtn())

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True


# ════════════════════════════════════════════════════════════
# /ตั้งโปรไฟล์บอท — เปลี่ยน avatar/banner per-guild (port จาก discord.js)
# ════════════════════════════════════════════════════════════
async def _fetch_image_bytes(url: str) -> tuple:
    """fetch URL → return (bytes, mime). raise ถ้าไม่ใช่รูปหรือใหญ่เกิน"""
    import aiohttp
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL ต้องขึ้นด้วย http:// หรือ https://")
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status} — ตรวจสอบ URL")
            ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
            if not ct.startswith("image/"):
                raise ValueError(f"ไม่ใช่รูปภาพ (content-type: {ct})")
            data = await resp.read()
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("รูปใหญ่เกิน 8MB")
            return data, ct


async def _patch_guild_member_self(guild_id: int, body: dict):
    """ส่ง PATCH /guilds/{guild_id}/members/@me เพื่อแก้ avatar/banner ของบอท per-guild"""
    import base64 as _b64
    from discord.http import Route
    # convert bytes → data URI ถ้ามี
    payload = {}
    for k in ("avatar", "banner"):
        if k not in body: continue
        v = body[k]
        if v is None:
            payload[k] = None
        else:
            data, mime = v   # tuple (bytes, mime)
            b64 = _b64.b64encode(data).decode("ascii")
            payload[k] = f"data:{mime};base64,{b64}"
    route = Route("PATCH", "/guilds/{guild_id}/members/@me", guild_id=guild_id)
    return await bot.http.request(route, json=payload)


@bot.tree.command(
    name="botprofile",
    description="[Admin] เปลี่ยน avatar/banner ของบอทเฉพาะเซิร์ฟนี้",
    guild=_ORION_GUILD_OBJ,
)
@discord.app_commands.describe(
    avatar_url="URL รูป avatar (เว้นว่างถ้าไม่เปลี่ยน)",
    banner_url="URL รูป banner (เว้นว่างถ้าไม่เปลี่ยน · อาจต้องการ Nitro)",
    reset="ติ๊ก = เคลียร์ avatar+banner กลับเป็น global default",
)
async def cmd_set_bot_profile(
    interaction: discord.Interaction,
    avatar_url: str = None,
    banner_url: str = None,
    reset: bool = False,
):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ไม่ได้", ephemeral=True); return
    if not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "❌ ต้องมีสิทธิ์ **Manage Server** ในเซิร์ฟนี้", ephemeral=True,
        ); return

    await interaction.response.defer(ephemeral=True)
    gid = interaction.guild.id

    # ── reset ──
    if reset:
        try:
            await _patch_guild_member_self(gid, {"avatar": None, "banner": None})
            await interaction.followup.send(
                "✅ **Reset profile** — avatar+banner กลับเป็น global default แล้ว",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(f"❌ Reset failed: `{e}`", ephemeral=True)
        return

    if not avatar_url and not banner_url:
        await interaction.followup.send(
            "ℹ️ ระบุ `avatar_url` หรือ `banner_url` อย่างน้อย 1 อัน (หรือติ๊ก `reset` เพื่อล้าง)",
            ephemeral=True,
        ); return

    lines = []
    body = {}
    if avatar_url:
        try:
            data, mime = await _fetch_image_bytes(avatar_url)
            body["avatar"] = (data, mime)
            lines.append(f"✅ Avatar — ดาวน์โหลดสำเร็จ ({len(data)//1024} KB, {mime})")
        except Exception as e:
            lines.append(f"❌ Avatar — `{e}`")

    if banner_url:
        try:
            data, mime = await _fetch_image_bytes(banner_url)
            body["banner"] = (data, mime)
            lines.append(f"✅ Banner — ดาวน์โหลดสำเร็จ ({len(data)//1024} KB, {mime})")
        except Exception as e:
            lines.append(f"❌ Banner — `{e}`")

    if body:
        try:
            await _patch_guild_member_self(gid, body)
            lines.append("\n🎉 **อัปเดต Discord สำเร็จ** — รีโหลดเซิร์ฟดูได้เลย")
        except Exception as e:
            err_msg = str(e)
            lines.append(f"\n❌ **Discord API error:** `{err_msg}`")
            if "banner" in body and "banner" in err_msg.lower():
                lines.append("> ⚠️ Banner per-guild ต้องการ **Nitro** ของบอท หรือต้องเป็น Verified Bot")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


@bot.tree.command(name="ตั้งคำสั่ง", description="[Admin] ติ๊กคำสั่งที่ต้องการให้ใช้ได้ในเซิร์ฟนี้", guild=_ORION_GUILD_OBJ)
async def cmd_enabled_cmds(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ไม่ได้", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    cfg = load_settings()
    enabled = cfg.get("enabled_commands", None)
    status = f"_เปิด **{len(enabled)}** คำสั่ง_" if enabled is not None else "_เปิดทุกคำสั่ง (default)_"
    embed = make_menu_embed(
        "Per-Guild Command Toggle",
        [
            status,
            ("วิธีใช้", "ติ๊ก dropdown ด้านล่างเฉพาะคำสั่งที่ต้องการให้ใช้ได้ในเซิร์ฟนี้\n_(ติ๊กว่าง = ไม่มีคำสั่งใช้ได้เลย)_\n_(ปุ่ม 'เปิดทุกคำสั่ง' = รีเซ็ตกลับ default)_"),
        ],
        color=0x95a5a6,
    )
    await interaction.response.send_message(embed=embed, view=EnabledCmdView(), ephemeral=True)


@bot.tree.command(name="setting", description="[Admin] ตั้งคำสั่งไหนให้ public / private", guild=_ORION_GUILD_OBJ)
async def cmd_setting(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    await interaction.response.send_message(
        embed=_build_setting_embed(),
        view=SettingView(),
        ephemeral=True,
    )


# ============================================================
# Guild allowlist + on_message + lifecycle
# ============================================================

class _OrionBlocked(commands.CheckFailure):
    pass


def _get_orion_allowed_command_names() -> set:
    allowed = set()
    for cat in HELP_CATEGORIES.values():
        if cat.get("guild") == ORION_GUILD_ID:
            for cmd_tuple in cat.get("commands", []):
                if isinstance(cmd_tuple, (list, tuple)) and cmd_tuple:
                    raw = str(cmd_tuple[0]).lstrip("?").strip().split()[0]
                    if raw:
                        allowed.add(raw)
    return allowed


@bot.check
async def _orion_guild_allowlist(ctx):
    if not ctx.guild or ctx.guild.id != ORION_GUILD_ID:
        return False
    if not ctx.command:
        return True
    if ctx.command.name in _get_orion_allowed_command_names():
        return True
    raise _OrionBlocked()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, _OrionBlocked):
        return
    if isinstance(error, commands.CommandNotFound):
        return
    if ctx.command and ctx.command.has_error_handler():
        return
    try:
        print(f"[CommandError] {ctx.command}: {type(error).__name__}: {error}")
        import traceback as _tb
        _tb.print_exception(type(error), error, error.__traceback__)
    except Exception:
        pass


@bot.event
async def on_message(message: discord.Message):
    # ข้ามข้อความบอท
    if message.author.bot:
        return

    # TRETARESIA quest thread handler — รับเฉพาะ Orion guild
    if (
        message.guild
        and message.guild.id == TRETARESIA_GUILD_ID
        and isinstance(message.channel, discord.Thread)
        and not message.content.startswith("?")
    ):
        tr_quests = _load_tr_quests()
        tr_q = tr_quests.get(str(message.channel.id))
        if tr_q and tr_q.get("status") == "active":
            uid = str(message.author.id)
            # ต้องเข้าร่วมก่อน
            if uid not in tr_q.get("team_ids", []):
                try:
                    await message.delete()
                except Exception:
                    pass
                await message.channel.send(
                    f"{message.author.mention} ใช้คำสั่ง `?trเข้าร่วม` ในเธรดนี้ก่อนเพื่อเข้าร่วมภารกิจ",
                    delete_after=8,
                )
                return

            tr_players = _load_tr_players()
            player_name = tr_players.get(uid, {}).get("char_name") or message.author.display_name
            player_ctx = _build_tr_player_context(uid, tr_players)

            team_ctx_lines = []
            for tid in tr_q.get("team_ids", []):
                if tid != uid:
                    ctx = _build_tr_player_context(tid, tr_players)
                    if ctx:
                        team_ctx_lines.append(ctx)

            parts = []
            if team_ctx_lines:
                parts.append("[ข้อมูลสมาชิกอื่นในทีม (AI รู้เท่านั้น ห้ามอ่านออก)]\n" + "\n".join(team_ctx_lines))
            if player_ctx:
                parts.append(player_ctx)
            parts.append(f"{player_name}: {message.content}")
            user_content = "\n".join(parts)

            tr_q["history"].append({"role": "user", "content": user_content})
            if len(tr_q["history"]) > 80:
                tr_q["history"] = tr_q["history"][-80:]

            async with message.channel.typing():
                reply = await _tr_ai_call(tr_q["history"])

            if reply.startswith("##TR_ERROR##"):
                tr_q["history"].pop()
                _save_tr_quests(tr_quests)
                await message.channel.send(f"⚠️ AI error: `{reply[13:]}`")
            else:
                tr_q["history"].append({"role": "assistant", "content": reply})
                _save_tr_quests(tr_quests)
                for chunk in [reply[i:i+1900] for i in range(0, len(reply), 1900)]:
                    await message.channel.send(chunk)
            return

    # ไม่เข้าเงื่อนไข quest thread → ส่งต่อให้ command processor
    await bot.process_commands(message)


# ════════════════════════════════════════════════════════════
# Security: lock bot to ORION_GUILD_ID only
# ════════════════════════════════════════════════════════════

# ── 1) Global slash check — set guild context + per-guild allow/disable ──
async def _global_slash_check(interaction: discord.Interaction) -> bool:
    if interaction.guild is None or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        try:
            await interaction.response.send_message(
                "❌ บอทไม่รองรับเซิร์ฟนี้",
                ephemeral=True,
            )
        except Exception:
            pass
        return False
    # set context สำหรับ per-guild data isolation
    _current_guild_id.set(interaction.guild.id)
    # check per-guild enabled commands
    cmd_name = interaction.command.name if interaction.command else None
    if cmd_name:
        cfg = load_settings()
        enabled = cfg.get("enabled_commands", None)
        # None = ทุกคำสั่งเปิด (default); list = ติ๊กเลือกแล้ว
        if enabled is not None and cmd_name not in enabled:
            try:
                await interaction.response.send_message(
                    f"❌ คำสั่ง `/{cmd_name}` ถูกปิดในเซิร์ฟนี้ (ใช้ `/ตั้งคำสั่ง` เพื่อเปิด)",
                    ephemeral=True,
                )
            except Exception:
                pass
            return False
    return True

bot.tree.interaction_check = _global_slash_check


def _is_guild_allowed(gid: int) -> bool:
    """guild ที่บอทอยู่ได้: main Orion + Guild2 + extra whitelist"""
    return gid in ALLOWED_COMMAND_GUILD_IDS or gid in ALLOWED_EXTRA_GUILD_IDS


# ── Command aliases (per-guild rename) ───────────────────────
COMMAND_ALIASES_FILE = f"{ORION_DATA_DIR}/cmd_aliases.json"


def load_cmd_aliases() -> dict:
    """{original_name: alias_name}"""
    return load_json(COMMAND_ALIASES_FILE, {})


def save_cmd_aliases(d: dict):
    save_json(COMMAND_ALIASES_FILE, d)


def _port_commands_to_guild2() -> int:
    """Copy Orion commands to Guild2 + **preserve Guild2-exclusive commands (AoT)**.
    - Identify commands ที่มีแต่ใน Guild2 (ไม่มีใน Orion) → save ก่อน clear
    - Clear Guild2 → port Orion (with aliases)
    - Re-add ของ Guild2-exclusive
    - Skip alias ที่จะ shadow Guild2-exclusive
    """
    from discord import app_commands

    orion_cmds = list(bot.tree.get_commands(guild=_ORION_GUILD_OBJ))
    orion_names = {c.name for c in orion_cmds}

    # ── Save Guild2-exclusive commands (AoT etc.) — ที่ไม่มีใน Orion ──
    guild2_dict = {}
    try:
        gd = getattr(bot.tree, "_guild_commands", {})
        guild2_dict = dict(gd.get(GUILD2_ID, {}))
    except Exception:
        pass
    extras = {name: cmd for name, cmd in guild2_dict.items() if name not in orion_names}

    # clear Guild2
    try:
        bot.tree.clear_commands(guild=_GUILD2_OBJ)
    except Exception:
        pass

    # load aliases (Guild2 context)
    token = _current_guild_id.set(GUILD2_ID)
    try:
        aliases = load_cmd_aliases()
    finally:
        _current_guild_id.reset(token)

    ported = 0
    aliased_count = 0
    skipped_shadow = []
    for cmd in orion_cmds:
        target_name = aliases.get(cmd.name, cmd.name)
        # ── ถ้า target name จะชนกับ Guild2-exclusive — skip ──
        if target_name in extras and target_name != cmd.name:
            skipped_shadow.append(f"/{cmd.name}→/{target_name}")
            continue
        if target_name in extras and target_name == cmd.name:
            # original name ชนกับ AoT → skip Orion version ปล่อยให้ AoT ครอง
            skipped_shadow.append(f"/{cmd.name}")
            continue
        try:
            if target_name != cmd.name:
                # ── สร้าง Command ใหม่ด้วย constructor (alias) ──
                callback = getattr(cmd, "_callback", None) or getattr(cmd, "callback", None)
                if callback is None:
                    print(f"[Port] {cmd.name}: ไม่มี callback ข้าม")
                    continue
                new_cmd = app_commands.Command(
                    name=target_name,
                    description=cmd.description or "—",
                    callback=callback,
                )
                for attr in ("_params", "extras", "_attr"):
                    if hasattr(cmd, attr):
                        try:
                            setattr(new_cmd, attr, getattr(cmd, attr))
                        except Exception:
                            pass
                bot.tree.add_command(new_cmd, guild=_GUILD2_OBJ, override=True)
                aliased_count += 1
            else:
                bot.tree.add_command(cmd, guild=_GUILD2_OBJ, override=True)
            ported += 1
        except Exception as e:
            print(f"[Port] {cmd.name}: {e}")

    # ── Re-add Guild2-exclusive commands (AoT) ──
    for name, cmd in extras.items():
        try:
            bot.tree.add_command(cmd, guild=_GUILD2_OBJ, override=True)
            ported += 1
        except Exception as e:
            print(f"[Port] re-add {name}: {e}")

    if aliased_count:
        print(f"[Port] Created {aliased_count} aliased commands (fresh)")
    if extras:
        print(f"[Port] Preserved {len(extras)} Guild2-exclusive: {', '.join(extras.keys())}")
    if skipped_shadow:
        print(f"[Port] Skipped (would shadow Guild2-exclusive): {', '.join(skipped_shadow)}")
    return ported


# ── /ชื่อคำสั่ง (Guild2 only) — view/rename/remove aliases ──
class CmdRenameSelect(discord.ui.Select):
    def __init__(self):
        # list all Orion commands (originals)
        orion_cmds = list(bot.tree.get_commands(guild=_ORION_GUILD_OBJ))[:25]
        aliases = load_cmd_aliases()
        options = []
        for cmd in orion_cmds:
            alias = aliases.get(cmd.name)
            label = f"/{cmd.name}" + (f"  →  /{alias}" if alias else "")
            options.append(discord.SelectOption(
                label=label[:100],
                value=cmd.name,
                description=(cmd.description or "—")[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีคำสั่ง", value="none")]
        super().__init__(placeholder="เลือกคำสั่งที่จะเปลี่ยนชื่อ...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        await ix.response.send_modal(CmdRenameModal(self.values[0]))


class CmdRenameModal(discord.ui.Modal, title="เปลี่ยนชื่อคำสั่ง"):
    f_new = discord.ui.TextInput(
        label="ชื่อใหม่ (เว้นว่าง = ลบ alias)",
        placeholder="a-z, 0-9, _ · 1-32 ตัว · ไม่มีช่องว่าง",
        required=False, max_length=32,
    )

    def __init__(self, original: str):
        super().__init__()
        self.original = original
        current = load_cmd_aliases().get(original, "")
        self.f_new.default = current
        self.title = f"เปลี่ยนชื่อ /{original}"[:45]

    async def on_submit(self, ix: discord.Interaction):
        new_name = (self.f_new.value or "").strip().lower()
        aliases = load_cmd_aliases()
        if not new_name:
            aliases.pop(self.original, None)
            verdict = f"ลบ alias `/{self.original}` แล้ว (กลับเป็นชื่อเดิม)"
        else:
            if " " in new_name:
                await ix.response.send_message("❌ ห้ามมีช่องว่าง (ใช้ _)", ephemeral=True); return
            aliases[self.original] = new_name
            verdict = f"บันทึก `/{self.original}` → `/{new_name}`"
        save_cmd_aliases(aliases)
        # ── ออกแบบใหม่: ไม่ auto-sync — บอกผู้ใช้ restart ──
        embed = discord.Embed(
            title="✅ บันทึก alias แล้ว",
            description=(
                f"{verdict}\n\n"
                "**ขั้นตอนต่อ — เลือก 1 จาก 2:**\n\n"
                "🔄 **A) Restart bot** (แนะนำ)\n"
                "→ SparkedHost panel → Restart\n"
                "→ on_ready จะ apply alias ทุกอันใหม่หมด\n\n"
                "⚡ **B) `/รีเฟรชคำสั่ง`** (เร็วแต่ไม่การันตี)\n"
                "→ Manual re-sync ทันที (อาจติด Discord cache)\n\n"
                "_หลังจากนั้น **Ctrl+R refresh Discord** เพื่อเห็นชื่อใหม่_"
            ),
            color=0x2ecc71,
        )
        await ix.response.send_message(embed=embed, ephemeral=True)


class CmdRenameView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(CmdRenameSelect())

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=1)
    async def done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)


@bot.tree.command(name="รีเฟรชคำสั่ง", description="[Admin · Guild2] Re-sync commands ทันที (ไม่ต้อง restart)", guild=_ORION_GUILD_OBJ)
async def cmd_refresh_commands(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != GUILD2_ID:
        await interaction.response.send_message(
            "❌ ใช้ได้เฉพาะใน **Guild2** เท่านั้น", ephemeral=True,
        ); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    try:
        ported = _port_commands_to_guild2()
        synced = await bot.tree.sync(guild=_GUILD2_OBJ)
        aliases = load_cmd_aliases()
        alias_lines = [f"`/{o}` → `/{n}`" for o, n in aliases.items()] or ["_(ไม่มี alias)_"]
        await interaction.followup.send(
            f"✅ Re-sync สำเร็จ\n"
            f"• Ported: `{ported}` commands\n"
            f"• Synced: `{len(synced)}` commands to Guild2\n\n"
            f"**Aliases ที่ apply:**\n" + "\n".join(alias_lines) + "\n\n"
            "_ถ้ายังไม่เห็นชื่อใหม่ใน Discord:_\n"
            "_1. **Ctrl+R** refresh client_\n"
            "_2. ถ้ายัง → Force quit Discord + เปิดใหม่_\n"
            "_3. ถ้ายัง → Restart bot ที่ SparkedHost_",
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Re-sync failed: `{e}`", ephemeral=True)


@bot.tree.command(name="ชื่อคำสั่ง", description="[Admin · Guild2] เปลี่ยนชื่อ slash command ในเซิร์ฟนี้", guild=_ORION_GUILD_OBJ)
async def cmd_rename_panel(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id != GUILD2_ID:
        await interaction.response.send_message(
            "❌ คำสั่งนี้ใช้ได้เฉพาะใน **Guild2** เท่านั้น (ปลายทาง ATTACK ON TITAN | WIP)",
            ephemeral=True,
        ); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    aliases = load_cmd_aliases()
    if aliases:
        lines = [f"`/{orig}` → `/{new}`" for orig, new in aliases.items()]
        alias_text = "\n".join(lines[:15])
    else:
        alias_text = "_(ยังไม่มี alias)_"
    embed = make_menu_embed(
        "เปลี่ยนชื่อคำสั่ง — Guild2",
        [
            ("Aliases ปัจจุบัน", alias_text),
            ("วิธีใช้", "เลือกคำสั่งจาก dropdown → กรอกชื่อใหม่ → ระบบ re-sync ให้อัตโนมัติ\n_(เว้นว่างใน modal = ลบ alias)_\n_(ตัวอักษรเล็ก, 1-32 ตัว, ไม่มีช่องว่าง)_"),
        ],
        color=0x9b59b6,
    )
    await interaction.response.send_message(embed=embed, view=CmdRenameView(), ephemeral=True)


# ============================================================
# LEADERBOARD
# ============================================================

@bot.tree.command(
    name="leaderboard",
    description="ดูรายชื่อผู้เล่นที่ร่ำรวยที่สุด | View the wealthiest players",
    guild=_ORION_GUILD_OBJ,
)
async def leaderboard_cmd(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    embed = _build_leaderboard_embed(interaction.guild, uid)
    await interaction.response.send_message(embed=embed, view=_LeaderboardView(uid, interaction.guild), ephemeral=_eph("leaderboard"))


def _build_leaderboard_embed(guild: discord.Guild, viewer_uid: str, show_hidden: bool = False) -> discord.Embed:
    players = load_orion_players()
    cfg     = load_currency_cfg()
    # Build sorted list
    entries = []
    hidden_ids = set()
    for uid, p in players.items():
        if p.get("lb_hidden") and not show_hidden:
            hidden_ids.add(uid)
            continue
        entries.append((uid, p.get("wallet", 0), p.get("char_name", "") or "?"))
    entries.sort(key=lambda x: x[1], reverse=True)

    embed = discord.Embed(
        title=f"🏆 Leaderboard — {cfg.get('name','Coins')}",
        color=0xf1c40f,
    )
    lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, wallet, char_name) in enumerate(entries[:10]):
        medal = medals[i] if i < 3 else f"`{i+1}`"
        member = guild.get_member(int(uid))
        display = member.display_name if member else f"<@{uid}>"
        lines.append(f"{medal} **{char_name}** ({display}) — {wallet:,} {cfg.get('symbol','')}")
    if lines:
        embed.description = "\n".join(lines)
    else:
        embed.description = "*No public entries.*"
    if hidden_ids:
        embed.set_footer(text=f"{len(hidden_ids)} player(s) have hidden themselves.")
    return embed


class _LeaderboardView(discord.ui.View):
    def __init__(self, uid: str, guild: discord.Guild):
        super().__init__(timeout=120)
        self.uid = uid; self.guild = guild
        p = load_orion_players().get(uid, {})
        is_hidden = p.get("lb_hidden", False)
        label = "Show My Name" if is_hidden else "Hide My Name"
        btn = discord.ui.Button(
            label=label,
            style=discord.ButtonStyle.secondary,
            emoji="👁️",
        )
        btn.callback = self._toggle_hide
        self.add_item(btn)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("Not your leaderboard.", ephemeral=True); return False
        return True

    async def _toggle_hide(self, ix: discord.Interaction):
        data = load_orion_players()
        p    = data.get(self.uid, {})
        p["lb_hidden"] = not p.get("lb_hidden", False)
        data[self.uid] = p
        save_orion_players(data)
        embed = _build_leaderboard_embed(self.guild, self.uid)
        # Update button label
        self.clear_items()
        is_hidden = p["lb_hidden"]
        label = "Show My Name" if is_hidden else "Hide My Name"
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, emoji="👁️")
        btn.callback = self._toggle_hide
        self.add_item(btn)
        await ix.response.edit_message(embed=embed, view=self)


# ============================================================
# GIMMICK ITEMS SYSTEM
# ============================================================

GIMMICK_DATA_FILE = f"{ORION_DATA_DIR}/gimmick_items.json"


def load_gimmick_items() -> dict:
    return load_json(GIMMICK_DATA_FILE, {})


def save_gimmick_items(d: dict):
    save_json(GIMMICK_DATA_FILE, d)


def _apply_gimmick_effect(uid: str, item_data: dict, guild: discord.Guild) -> str:
    """Apply the gimmick item effect and return a description of what happened."""
    effect = item_data.get("effect_type", "")
    result = ""

    if effect == "skill_grant":
        category_id = item_data.get("effect_category", "any")
        qty         = int(item_data.get("effect_qty", 1))
        grant_skill_slot(uid, category_id, qty)
        cat_name = category_id if category_id != "any" else "Any"
        result = f"Granted {qty} skill slot(s) in category: **{cat_name}**"

    elif effect == "exp_boost":
        import time
        duration_h = int(item_data.get("effect_duration_hours", 24))
        multiplier = float(item_data.get("effect_multiplier", 2.0))
        try:
            import orion_stats
            cfg = orion_stats.load_stats_config()
            boosts = cfg.setdefault("exp_boosts", {})
            expires = time.time() + duration_h * 3600 if duration_h > 0 else 0
            boosts[uid] = {"multiplier": multiplier, "expires_at": expires}
            orion_stats.save_stats_config(cfg)
            dur_str = f"{duration_h}h" if duration_h > 0 else "permanent"
            result = f"EXP Boost x{multiplier} active for **{dur_str}**"
        except Exception as e:
            result = f"EXP Boost applied (error: {e})"

    elif effect == "drop_boost":
        import time
        duration_h = int(item_data.get("effect_duration_hours", 24))
        multiplier = float(item_data.get("effect_multiplier", 2.0))
        data = load_orion_players()
        p    = data.get(uid, {})
        expires = time.time() + duration_h * 3600 if duration_h > 0 else 0
        p["drop_boost"] = {"multiplier": multiplier, "expires_at": expires}
        data[uid] = p
        save_orion_players(data)
        dur_str = f"{duration_h}h" if duration_h > 0 else "permanent"
        result = f"Drop Rate Boost x{multiplier} active for **{dur_str}**"

    elif effect == "guild_slot":
        qty = int(item_data.get("effect_qty", 1))
        try:
            import orion_familia
            orion_familia.add_guild_slots(uid, guild, qty)
            result = f"Added {qty} guild slot(s)"
        except Exception as e:
            result = f"Guild slot(s) added (error: {e})"

    else:
        result = "No effect."

    return result


class _GimmickUseView(discord.ui.View):
    """Shown when player uses a gimmick item."""
    def __init__(self, uid: str, item_key: str, item_data: dict, guild: discord.Guild):
        super().__init__(timeout=120)
        self.uid = uid; self.item_key = item_key; self.item_data = item_data; self.guild = guild

    @discord.ui.button(label="Use Item", style=discord.ButtonStyle.success, emoji="✨")
    async def btn_use(self, ix: discord.Interaction, _b):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("Not your item.", ephemeral=True); return
        # Remove 1 from inventory
        import orion_items as _oi
        _oi.remove_player_item(self.uid, self.item_key, 1)
        result = _apply_gimmick_effect(self.uid, self.item_data, self.guild)
        embed = discord.Embed(
            title=f"✨ Used: {self.item_data.get('name','?')}",
            description=result,
            color=discord.Color.gold(),
        )
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def btn_cancel(self, ix: discord.Interaction, _b):
        if str(ix.user.id) != self.uid:
            await ix.response.send_message("Not your item.", ephemeral=True); return
        await ix.response.edit_message(
            embed=discord.Embed(description="Cancelled.", color=discord.Color.orange()),
            view=None,
        )


# Admin: Create gimmick items
@bot.tree.command(
    name="กิมมิคไอเทม",
    description="[Admin] สร้าง/จัดการ Gimmick Items ที่มีเอฟเฟกต์พิเศษ",
    guild=_ORION_GUILD_OBJ,
)
async def gimmick_admin_cmd(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ไม่สามารถใช้ได้", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Admin only", ephemeral=True); return
    embed = discord.Embed(
        title="Gimmick Items Admin",
        description="Create special items with unique effects.",
        color=0x9b59b6,
    )
    await interaction.response.send_message(embed=embed, view=_GimmickAdminView(), ephemeral=True)


class _GimmickAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Create Gimmick Item", style=discord.ButtonStyle.success, emoji="➕")
    async def btn_create(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_GimmickCreateModal())

    @discord.ui.button(label="List Gimmick Items", style=discord.ButtonStyle.secondary, emoji="📋")
    async def btn_list(self, ix: discord.Interaction, _b):
        items = load_gimmick_items()
        if not items:
            embed = discord.Embed(description="No gimmick items created yet.", color=0x9b59b6)
        else:
            lines = []
            for key, d in items.items():
                lines.append(f"• **{d.get('name','?')}** (`{key}`) — {d.get('effect_type','?')}")
            embed = discord.Embed(title="Gimmick Items", description="\n".join(lines[:25]), color=0x9b59b6)
        await ix.response.edit_message(embed=embed, view=self)


class _GimmickCreateModal(discord.ui.Modal, title="Create Gimmick Item"):
    f_name     = discord.ui.TextInput(label="Item Name", max_length=60)
    f_emoji    = discord.ui.TextInput(label="Emoji/Icon", max_length=50, required=False)
    f_desc     = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=300)
    f_effect   = discord.ui.TextInput(
        label="Effect Type (skill_grant/exp_boost/drop_boost/guild_slot)",
        max_length=30,
    )
    f_params   = discord.ui.TextInput(
        label="Effect Params (JSON: category/multiplier/duration_hours/qty)",
        style=discord.TextStyle.paragraph, max_length=200,
    )

    async def on_submit(self, ix: discord.Interaction):
        import json as _json
        import re as _re
        import uuid as _uuid
        name   = self.f_name.value.strip()
        emoji  = self.f_emoji.value.strip() or "✨"
        desc   = self.f_desc.value.strip()
        effect = self.f_effect.value.strip()
        try:
            params = _json.loads(self.f_params.value.strip()) if self.f_params.value.strip() else {}
        except Exception:
            params = {}
        key = _re.sub(r"[^\w]+", "_", name.lower()) + "_" + _uuid.uuid4().hex[:4]
        item_data = {
            "name":        name,
            "emoji":       emoji,
            "description": desc,
            "effect_type": effect,
            "item_type":   "gimmick",
            "rarity":      "Special",
            **params,
        }
        items = load_gimmick_items()
        items[key] = item_data
        save_gimmick_items(items)
        # Also add to main items catalog
        try:
            catalog = load_json(f"{ORION_DATA_DIR}/items_catalog.json", {})
            catalog[key] = item_data
            save_json(f"{ORION_DATA_DIR}/items_catalog.json", catalog)
        except Exception:
            pass
        embed = discord.Embed(
            title="Gimmick Item Created",
            description=f"**{name}** (`{key}`) — Effect: {effect}",
            color=discord.Color.green(),
        )
        await ix.response.edit_message(embed=embed, view=_GimmickAdminView())


# ============================================================
# HELP / GUIDE COMMAND
# ============================================================

@bot.tree.command(
    name="guide",
    description="คู่มือการใช้งานบอท Orion ทั้งหมด | Full bot guide / instructions",
    guild=_ORION_GUILD_OBJ,
)
async def guide_cmd(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    embed = discord.Embed(
        title="Orion Bot — Guide & Commands",
        description="Select a category to view commands and instructions.",
        color=0x6c5ce7,
    )
    await interaction.response.send_message(embed=embed, view=_GuideView(), ephemeral=True)


class _GuideView(discord.ui.View):
    PAGES = {
        "Player": [
            ("/orion", "View your character profile, skills, stats, and inventory"),
            ("/ไอเทม", "View your item inventory"),
            ("/เงิน", "Check your wallet balance"),
            ("/โอนเงิน", "Transfer coins to another player"),
            ("/guild", "View and manage your Guild/Familia"),
            ("/ฝึกสถิติ", "Train your attributes (Strength, Endurance, Speed, Perception) via mini-games"),
            ("/ภารกิจ", "View and join missions on the mission board"),
            ("/สร้าง", "Craft Artifact Skills or items (requires creation role)"),
            ("/leaderboard", "View the richest players leaderboard"),
            ("/guide", "Show this help guide"),
        ],
        "Character": [
            ("Character Creation", "Use /orion → Create Character. Fill in 2 modals (basic info + personality), select first skill type. Admin reviews and approves."),
            ("Skill Creation", "Use /orion → Create Skill. Fill in skill details. Admin reviews — can approve, decline, or request revision."),
            ("Edit Character", "Use /orion → Edit Character to update name, image, appearance, role/gender/race."),
            ("Delete Character", "Use /orion → Delete Character. Removes all data (irreversible)."),
        ],
        "Skills & Stats": [
            ("Skills Panel", "View all skills with pagination. Select a skill to see full details (name, description, rank, cooldown, drawback)."),
            ("Stats Training", "Choose attribute → play minigame → earn XP → rank up. Cooldown between sessions. Ranks: E- to EX."),
            ("Skill Types", "Artifact (physical objects), Aura (energy/spiritual), False Magic (illusion/tricks)"),
            ("Skill Grants", "Granted by admin or from special items. Shows on /orion profile if available."),
        ],
        "Admin": [
            ("/ตั้งคำสั่ง", "Toggle commands on/off"),
            ("/setting", "Toggle public/private command visibility"),
            ("/เงินแอดมิน", "Grant, remove, or check player balances"),
            ("/คราฟแอดมิน", "Manage the creation/crafting system — set roles, review channel"),
            ("/ฝึกสถิติแอดมิน", "Configure stats: rank cap, cooldown, EXP gain, EXP boost, admin-edit player stats"),
            ("/ภารกิจแอดมิน", "Create, edit, and manage missions on the board"),
            ("/กิมมิคไอเทม", "Create gimmick items with special effects (skill grants, EXP boost, drop boost, guild slots)"),
            ("/guild (admin)", "Manage guild/familia settings, members, roles"),
            ("/คำขอสกิล", "Review skill creation requests (approve/decline/edit)"),
        ],
        "Economy & Items": [
            ("Wallet", "Each player has a wallet. Earn coins from jobs, missions, trading."),
            ("Transfer", "Use /โอนเงิน or /orion → Transfer to send coins to other players."),
            ("Shop", "Buy items from the shop with /shop"),
            ("Crafting", "Use /สร้าง to craft items using materials from inventory. Select materials from dropdown, write description, submit for admin review."),
            ("Inventory", "Use /ไอเทม to view inventory. Items show name, quantity, description."),
        ],
    }

    def __init__(self):
        super().__init__(timeout=300)
        sel = discord.ui.Select(
            placeholder="Select a category...",
            options=[
                discord.SelectOption(label=cat, value=cat)
                for cat in self.PAGES
            ],
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        cat = ix.data["values"][0]
        items = self.PAGES.get(cat, [])
        embed = discord.Embed(
            title=f"Guide — {cat}",
            color=0x6c5ce7,
        )
        for cmd, desc in items:
            embed.add_field(name=cmd, value=desc, inline=False)
        await ix.response.edit_message(embed=embed, view=self)


# ── 2) Auto-leave foreign guilds (ยกเว้น whitelist) ──
@bot.event
async def on_guild_join(guild):
    if not _is_guild_allowed(guild.id):
        print(f"[Security] Auto-leaving foreign guild {guild.id} ({guild.name})")
        try:
            await guild.leave()
        except Exception as e:
            print(f"[Security] Failed to leave guild {guild.id}: {e}")
    else:
        print(f"[Security] Allowed guild joined: {guild.id} ({guild.name})")


@bot.event
async def on_ready():
    print(f"✅ บอทออนไลน์แล้วในชื่อ {bot.user}")
    # ── 3) Leave any foreign guilds (ยกเว้น whitelist) ──
    for g in list(bot.guilds):
        if not _is_guild_allowed(g.id):
            print(f"[Security] Leaving foreign guild {g.id} ({g.name})")
            try:
                await g.leave()
            except Exception as e:
                print(f"[Security] Failed: {e}")
        else:
            print(f"[Security] Allowed guild: {g.id} ({g.name})")

    # ── 4) Wipe global slash commands (กันรั่วไปเซิร์ฟอื่น) ──
    try:
        bot.tree.clear_commands(guild=None)
        global_synced = await bot.tree.sync()
        print(f"[Security] Wiped global commands → {len(global_synced)} remaining")
    except Exception as e:
        print(f"[Security] Global wipe failed: {e}")

    # ── 5) PORT DISABLED — Guild2 ใช้คำสั่งของตัวเองเท่านั้น (AoT) ──
    # อยากเปิด port กลับมา: uncomment 2 บรรทัดนี้
    # try: ported = _port_commands_to_guild2()
    # except Exception as e: print(f"[Port] failed: {e}")

    # ── 6) Sync slash commands ──
    try:
        s1 = await bot.tree.sync(guild=_ORION_GUILD_OBJ)
        print(f"[Slash] synced {len(s1)} commands to Orion guild")
    except Exception as e:
        print(f"[Slash] Orion sync failed: {e}")
    try:
        s2 = await bot.tree.sync(guild=_GUILD2_OBJ)
        print(f"[Slash] synced {len(s2)} commands to Guild2 (AoT only)")
    except Exception as e:
        print(f"[Slash] Guild2 sync failed: {e}")

    if not orion_weather_task.is_running():
        orion_weather_task.start()

    # Start Familia passive income loop
    try:
        if not orion_familia.familia_passive_loop.is_running():
            orion_familia.familia_passive_loop.start()
            print("[Familia] passive income loop started")
    except Exception as e:
        print(f"[Familia] passive loop start failed: {e}")

    # Start AoT shifter background tasks (Guild2 only)
    try:
        aot_shifter.start_tasks()
        print("[AoT] shifter tasks started")
    except Exception as e:
        print(f"[AoT] shifter tasks failed: {e}")

    # Start AoT shop restock task (Guild2 only)
    try:
        aot_shop.start_shop_tasks()
        print("[AoT] shop restock task started")
    except Exception as e:
        print(f"[AoT] shop restock task failed: {e}")

    # Start AoT job passive-income task (Guild2 only)
    try:
        aot_job.start_job_tasks()
        print("[AoT] job passive-income task started")
    except Exception as e:
        print(f"[AoT] job task failed: {e}")

    async def _orion_restart_refresh():
        try:
            await asyncio.sleep(5)
            await _post_orion_weather_update(edit_only=True)
        except Exception as e:
            print(f"[Orion Weather] restart refresh failed: {e}")
    asyncio.create_task(_orion_restart_refresh())


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    # ถ้ามีตั้ง env var DISCORD_TOKEN ใน panel จะใช้ค่านั้นก่อน
    # ถ้าไม่มี จะ fallback ใช้ token ที่ฝังไว้ในโค้ดด้านล่าง
    token = os.environ.get("ORION_TOKEN") or os.environ.get("DISCORD_TOKEN")
    if not token:
        print("❌ ไม่พบ token — กรุณาตั้ง ORION_TOKEN หรือ DISCORD_TOKEN")
        sys.exit(1)
    bot.run(token)
