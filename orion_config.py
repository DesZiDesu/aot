# ============================================================
# ORION — Unified /config command (10 pages)
# ============================================================
# หน้า 1: General           — currency, language
# หน้า 2: Channels          — mission board, review channel, registration role
# หน้า 3: Character Creation — forum channel, admin role, auto-assign role
# หน้า 4: Stats Training     — rank cap, training cost, cooldown, exceed-cap roles
# หน้า 5: Shop              — note + category count
# หน้า 6: Scavenge          — note + /คลังไอเทม cooldown
# หน้า 7: Jobs              — note + job count
# หน้า 8: Creation System   — creation roles, review channel
# หน้า 9: Character Options  — race/gender/occupation lists + role assignments
# หน้า 10: Logs              — log channel setup
# ============================================================

import sys
import discord
from discord import app_commands

# ── ดึง dependencies จาก orion_bot ────────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_config ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                       = _orion_bot_mod.bot
ORION_GUILD_ID            = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ          = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR            = _orion_bot_mod.ORION_DATA_DIR
load_json                 = _orion_bot_mod.load_json
save_json                 = _orion_bot_mod.save_json
load_currency_cfg         = _orion_bot_mod.load_currency_cfg
save_currency_cfg         = _orion_bot_mod.save_currency_cfg
money_str                 = _orion_bot_mod.money_str
_parse_int                = _orion_bot_mod._parse_int


# ============================================================
# DATA FILE PATHS
# ============================================================

_STATS_CFG_FILE    = f"{ORION_DATA_DIR}/stats_config.json"
_CREATION_CFG_FILE = f"{ORION_DATA_DIR}/creation_config.json"
_MISSIONS_CFG_FILE = f"{ORION_DATA_DIR}/missions_config.json"
_JOBS_FILE         = f"{ORION_DATA_DIR}/jobs.json"
_SCAVENGE_FILE     = f"{ORION_DATA_DIR}/scavenge_pools.json"
_SHOP_CATALOG_FILE = f"{ORION_DATA_DIR}/shop_catalog.json"
_ITEMS_CFG_FILE    = f"{ORION_DATA_DIR}/items_config.json"
_CHAR_OPTIONS_FILE = f"{ORION_DATA_DIR}/char_options.json"
_LOG_CFG_FILE      = f"{ORION_DATA_DIR}/logs_config.json"

_TOTAL_PAGES = 10

# Rank options for stats
_RANKS = [
    "E-", "E", "E+",
    "D-", "D", "D+",
    "C-", "C", "C+",
    "B-", "B", "B+",
    "A-", "A", "A+",
    "S-", "S", "S+",
    "EX",
]


# ============================================================
# DATA HELPERS
# ============================================================

def _load_stats_cfg() -> dict:
    cfg = load_json(_STATS_CFG_FILE, {})
    for k, v in [
        ("rank_cap",            "B+"),
        ("training_cost",       50),
        ("cooldown_seconds",    3600),
        ("exceed_cap_role_ids", []),
    ]:
        cfg.setdefault(k, v)
    return cfg


def _save_stats_cfg(cfg: dict):
    save_json(_STATS_CFG_FILE, cfg)


def _load_creation_cfg() -> dict:
    cfg = load_json(_CREATION_CFG_FILE, {})
    for k, v in [
        ("creation_role_ids",  []),
        ("review_channel_id",  None),
        ("forum_channel_id",   None),
        ("admin_role_ids",     []),
        ("auto_assign_role_id", None),
        ("registration_role_id", None),
    ]:
        cfg.setdefault(k, v)
    return cfg


def _save_creation_cfg(cfg: dict):
    save_json(_CREATION_CFG_FILE, cfg)


def _load_missions_cfg() -> dict:
    cfg = load_json(_MISSIONS_CFG_FILE, {})
    cfg.setdefault("board_channel_ids", [])
    cfg.setdefault("admin_role_ids", [])
    return cfg


def _save_missions_cfg(cfg: dict):
    save_json(_MISSIONS_CFG_FILE, cfg)


def _load_items_cfg() -> dict:
    cfg = load_json(_ITEMS_CFG_FILE, {})
    cfg.setdefault("search_cooldown_seconds", 0)
    return cfg


def _save_items_cfg(cfg: dict):
    save_json(_ITEMS_CFG_FILE, cfg)


def _load_jobs() -> dict:
    return load_json(_JOBS_FILE, {"jobs": {}})


def _load_shop_catalog() -> dict:
    return load_json(_SHOP_CATALOG_FILE, {"categories": [], "items": []})


def _load_char_options_cfg() -> dict:
    opts = load_json(_CHAR_OPTIONS_FILE, None)
    if opts is None:
        opts = {"genders": [], "races": [], "occupations": [], "approved_role_ids": []}
        save_json(_CHAR_OPTIONS_FILE, opts)
    for k, v in [("genders", []), ("races", []), ("occupations", []), ("approved_role_ids", [])]:
        opts.setdefault(k, v)
    return opts


def _save_char_options_cfg(d: dict):
    save_json(_CHAR_OPTIONS_FILE, d)


def _load_log_cfg() -> dict:
    cfg = load_json(_LOG_CFG_FILE, {})
    cfg.setdefault("log_channel_id", None)
    cfg.setdefault("enabled", True)
    return cfg


def _save_log_cfg(cfg: dict):
    save_json(_LOG_CFG_FILE, cfg)


# ============================================================
# DISPLAY HELPERS
# ============================================================

def _ch_mention(cid) -> str:
    if not cid:
        return "_ยังไม่ได้ตั้งค่า_"
    return f"<#{cid}>"


def _role_mention(rid) -> str:
    if not rid:
        return "_ยังไม่ได้ตั้งค่า_"
    return f"<@&{rid}>"


def _role_list(rids: list) -> str:
    if not rids:
        return "_ยังไม่มี_"
    return " ".join(f"<@&{r}>" for r in rids[:10])


def _ch_list(cids: list) -> str:
    if not cids:
        return "_ยังไม่มี_"
    return " ".join(f"<#{c}>" for c in cids[:10])


# ============================================================
# MODALS
# ============================================================

class _CurrencyModal(discord.ui.Modal, title="⚙️ ตั้งค่าเงินและภาษา"):
    f_name  = discord.ui.TextInput(label="ชื่อค่าเงิน", placeholder="เช่น Aurum / Gold", max_length=30)
    f_emoji = discord.ui.TextInput(label="Emoji", placeholder="💰 🪙 💎", max_length=10)
    f_icon  = discord.ui.TextInput(label="Icon URL (ไม่บังคับ)", required=False, max_length=400)
    f_start = discord.ui.TextInput(label="เงินเริ่มต้นผู้เล่นใหม่", placeholder="100", max_length=10)

    def __init__(self, parent: "ConfigView"):
        super().__init__()
        self.parent = parent
        cfg = load_currency_cfg()
        self.f_name.default  = cfg.get("name", "Aurum")
        self.f_emoji.default = cfg.get("emoji", "💰")
        self.f_icon.default  = cfg.get("icon_url", "")
        self.f_start.default = str(cfg.get("start_balance", 100))

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_currency_cfg()
        cfg["name"]          = self.f_name.value.strip() or "Aurum"
        cfg["emoji"]         = self.f_emoji.value.strip() or "💰"
        cfg["icon_url"]      = (self.f_icon.value or "").strip()
        cfg["start_balance"] = max(0, _parse_int(self.f_start.value, 100) or 100)
        save_currency_cfg(cfg)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _RankCapModal(discord.ui.Modal, title="⚙️ ตั้ง Rank Cap"):
    f_cap = discord.ui.TextInput(
        label="Rank Cap (เช่น B+, A-, EX)",
        placeholder="B+",
        max_length=4,
    )

    def __init__(self, parent: "ConfigView"):
        super().__init__()
        self.parent = parent
        cfg = _load_stats_cfg()
        self.f_cap.default = cfg.get("rank_cap", "B+")

    async def on_submit(self, ix: discord.Interaction):
        val = self.f_cap.value.strip().upper()
        if val not in _RANKS:
            await ix.response.send_message(
                f"❌ Rank ไม่ถูกต้อง ต้องเป็น: {', '.join(_RANKS)}",
                ephemeral=True,
            )
            return
        cfg = _load_stats_cfg()
        cfg["rank_cap"] = val
        _save_stats_cfg(cfg)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _TrainingCostModal(discord.ui.Modal, title="⚙️ ตั้งค่าการฝึก"):
    f_cost    = discord.ui.TextInput(label="ค่าใช้จ่ายต่อครั้ง (ตัวเลข)", max_length=10)
    f_cd      = discord.ui.TextInput(label="Cooldown (วินาที)", max_length=10)

    def __init__(self, parent: "ConfigView"):
        super().__init__()
        self.parent = parent
        cfg = _load_stats_cfg()
        self.f_cost.default = str(cfg.get("training_cost", 50))
        self.f_cd.default   = str(cfg.get("cooldown_seconds", 3600))

    async def on_submit(self, ix: discord.Interaction):
        cfg  = _load_stats_cfg()
        cost = _parse_int(self.f_cost.value, None)
        cd   = _parse_int(self.f_cd.value, None)
        if cost is None or cost < 0:
            await ix.response.send_message("❌ ค่าใช้จ่ายต้องเป็นตัวเลขที่ไม่ติดลบ", ephemeral=True)
            return
        if cd is None or cd < 0:
            await ix.response.send_message("❌ Cooldown ต้องเป็นตัวเลขที่ไม่ติดลบ", ephemeral=True)
            return
        cfg["training_cost"]    = cost
        cfg["cooldown_seconds"] = cd
        _save_stats_cfg(cfg)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _ForumChannelModal(discord.ui.Modal, title="⚙️ ตั้ง Forum Channel ID"):
    f_id = discord.ui.TextInput(
        label="Forum Channel ID (ตัวเลข)",
        placeholder="เช่น 1234567890123456789",
        max_length=25,
        required=False,
    )

    def __init__(self, parent: "ConfigView"):
        super().__init__()
        self.parent = parent
        cfg = _load_creation_cfg()
        fid = cfg.get("forum_channel_id")
        self.f_id.default = str(fid) if fid else ""

    async def on_submit(self, ix: discord.Interaction):
        raw = self.f_id.value.strip()
        fid = _parse_int(raw, None) if raw else None
        cfg = _load_creation_cfg()
        cfg["forum_channel_id"] = fid
        _save_creation_cfg(cfg)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _ScavengeCooldownModal(discord.ui.Modal, title="⚙️ Cooldown /คลังไอเทม (วินาที)"):
    f_cd = discord.ui.TextInput(
        label="Cooldown วินาที (0 = ไม่จำกัด)",
        placeholder="0",
        max_length=10,
    )

    def __init__(self, parent: "ConfigView"):
        super().__init__()
        self.parent = parent
        cfg = _load_items_cfg()
        self.f_cd.default = str(cfg.get("search_cooldown_seconds", 0))

    async def on_submit(self, ix: discord.Interaction):
        cd = _parse_int(self.f_cd.value, None)
        if cd is None or cd < 0:
            await ix.response.send_message("❌ Cooldown ต้องเป็นตัวเลขที่ไม่ติดลบ", ephemeral=True)
            return
        cfg = _load_items_cfg()
        cfg["search_cooldown_seconds"] = cd
        _save_items_cfg(cfg)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


# ============================================================
# EMBEDS PER PAGE
# ============================================================

def _build_page_embed(page: int) -> discord.Embed:
    color = 0x5865f2

    # ── Page 1: General ─────────────────────────────────────
    if page == 1:
        cfg  = load_currency_cfg()
        lang = cfg.get("language", "th")
        lang_display = "🇹🇭 Thai" if lang == "th" else "🇬🇧 English"
        embed = discord.Embed(
            title="⚙️ Config — หน้า 1: ทั่วไป (General)",
            color=color,
        )
        icon = cfg.get("icon_url", "")
        embed.description = (
            f"**ชื่อค่าเงิน:** {cfg.get('name','—')}\n"
            f"**Emoji:** {cfg.get('emoji','—')}\n"
            f"**Icon URL:** {icon if icon else '_ไม่ได้ตั้งค่า_'}\n"
            f"**เงินเริ่มต้นผู้เล่นใหม่:** `{cfg.get('start_balance', 100):,}`\n"
            f"**ภาษา:** {lang_display}\n"
        )
        if icon:
            embed.set_thumbnail(url=icon)
        return embed

    # ── Page 2: Channels ────────────────────────────────────
    if page == 2:
        mc  = _load_missions_cfg()
        cc  = _load_creation_cfg()
        embed = discord.Embed(
            title="⚙️ Config — หน้า 2: ห้อง (Channels)",
            color=color,
        )
        embed.description = (
            f"**Mission Board Channels:**\n{_ch_list(mc.get('board_channel_ids', []))}\n\n"
            f"**Admin Review Channel (Creation):**\n{_ch_mention(cc.get('review_channel_id'))}\n\n"
            f"**Registration Role (ได้รับเมื่อ approve ตัวละคร):**\n"
            f"{_role_mention(cc.get('registration_role_id'))}\n"
        )
        return embed

    # ── Page 3: Character Creation ──────────────────────────
    if page == 3:
        cc = _load_creation_cfg()
        embed = discord.Embed(
            title="⚙️ Config — หน้า 3: สร้างตัวละคร (Character Creation)",
            color=color,
        )
        embed.description = (
            f"**Forum Channel ID:**\n{_ch_mention(cc.get('forum_channel_id'))}\n\n"
            f"**Admin Role สำหรับตรวจสอบ:**\n{_role_list(cc.get('admin_role_ids', []))}\n\n"
            f"**Auto-assign Role เมื่อ Approve:**\n"
            f"{_role_mention(cc.get('auto_assign_role_id'))}\n"
        )
        return embed

    # ── Page 4: Stats Training ──────────────────────────────
    if page == 4:
        sc = _load_stats_cfg()
        embed = discord.Embed(
            title="⚙️ Config — หน้า 4: ฝึกสถิติ (Stats Training)",
            color=color,
        )
        embed.description = (
            f"**Rank Cap:** `{sc.get('rank_cap', 'B+')}`\n"
            f"**Training Cost:** `{sc.get('training_cost', 50):,}` ต่อครั้ง\n"
            f"**Cooldown:** `{sc.get('cooldown_seconds', 3600):,}` วินาที\n"
            f"**Exceed-cap Roles** (ฝึกเกิน cap ได้):\n"
            f"{_role_list(sc.get('exceed_cap_role_ids', []))}\n"
        )
        return embed

    # ── Page 5: Shop ─────────────────────────────────────────
    if page == 5:
        catalog = _load_shop_catalog()
        cat_count = len(catalog.get("categories", []))
        embed = discord.Embed(
            title="⚙️ Config — หน้า 5: ร้านค้า (Shop)",
            color=color,
        )
        embed.description = (
            "ตั้งค่าร้านค้าผ่าน **`/ร้านแอดมิน`**\n\n"
            f"**หมวดหมู่ปัจจุบัน:** `{cat_count}` หมวด\n"
        )
        return embed

    # ── Page 6: Scavenge ─────────────────────────────────────
    if page == 6:
        ic  = _load_items_cfg()
        cd  = ic.get("search_cooldown_seconds", 0)
        embed = discord.Embed(
            title="⚙️ Config — หน้า 6: หาของ (Scavenge)",
            color=color,
        )
        embed.description = (
            "ตั้งค่าห้องผ่าน **`/หาของห้อง`** และ **`/หาของแอดมิน`**\n\n"
            f"**Cooldown /คลังไอเทม:** `{cd:,}` วินาที"
            + (" _(ไม่จำกัด)_" if cd == 0 else "") + "\n"
        )
        return embed

    # ── Page 7: Jobs ─────────────────────────────────────────
    if page == 7:
        jobs_data = _load_jobs()
        job_count = len(jobs_data.get("jobs", {}))
        embed = discord.Embed(
            title="⚙️ Config — หน้า 7: งาน (Jobs)",
            color=color,
        )
        embed.description = (
            "ตั้งค่างานผ่าน **`/งาน-แอดมิน`**\n\n"
            f"**งานปัจจุบัน:** `{job_count}` งาน\n"
        )
        return embed

    # ── Page 8: Creation System ──────────────────────────────
    if page == 8:
        cc = _load_creation_cfg()
        embed = discord.Embed(
            title="⚙️ Config — หน้า 8: ระบบ Creation (Blacksmith)",
            color=color,
        )
        embed.description = (
            f"**Blacksmith/Creation Roles:**\n{_role_list(cc.get('creation_role_ids', []))}\n\n"
            f"**Review Channel:**\n{_ch_mention(cc.get('review_channel_id'))}\n"
        )
        return embed

    # ── Page 9: Character Options ─────────────────────────────
    if page == 9:
        opts = _load_char_options_cfg()
        genders     = opts.get("genders", [])
        races       = opts.get("races", [])
        occupations = opts.get("occupations", [])
        approved    = opts.get("approved_role_ids", [])

        def _fmt_list(items):
            if not items:
                return "_ยังไม่มี_"
            lines = []
            for o in items[:15]:
                lbl = o.get("label", "?")
                rid = o.get("role_id")
                lines.append(f"• {lbl}" + (f" → <@&{rid}>" if rid else ""))
            return "\n".join(lines)

        embed = discord.Embed(
            title="⚙️ Config — หน้า 9: ตัวเลือกตัวละคร (Character Options)",
            color=color,
        )
        embed.description = (
            "จัดการ dropdown ที่ผู้เล่นเห็นตอนสร้างตัวละคร\n"
            "แต่ละตัวเลือกสามารถผูก Discord Role ได้\n\n"
            f"**เพศ ({len(genders)} ตัวเลือก):**\n{_fmt_list(genders)}\n\n"
            f"**เผ่าพันธุ์ ({len(races)} ตัวเลือก):**\n{_fmt_list(races)}\n\n"
            f"**ชั้น/อาชีพ ({len(occupations)} ตัวเลือก):**\n{_fmt_list(occupations)}\n\n"
            f"**Roles เมื่อ Approve (ทุกคน):**\n{_role_list(approved)}"
        )
        return embed

    # ── Page 10: Logs ─────────────────────────────────────────
    if page == 10:
        log_cfg = _load_log_cfg()
        ch_id   = log_cfg.get("log_channel_id")
        enabled = log_cfg.get("enabled", True)
        embed = discord.Embed(
            title="⚙️ Config — หน้า 10: ระบบ Logs",
            color=color,
        )
        embed.description = (
            f"**Log Channel:**\n{_ch_mention(ch_id)}\n\n"
            f"**สถานะ Logs:** {'🟢 เปิดอยู่' if enabled else '🔴 ปิดอยู่'}\n\n"
            "ระบบ Logs ติดตามทุกกิจกรรมของผู้เล่น:\n"
            "💰 รับ/จ่ายเงิน · 📊 Rank สถิติขึ้น · 🔨 คราฟ · ✨ สร้างสกิล\n"
            "⚙️ โอนสกิล · ✅ ตัวละครผ่าน · 🗑️ ลบตัวละคร · 📦 รับไอเทม\n\n"
            "_ใช้ `/logsแอดมิน` เพื่อตั้งค่าช่อง Log โดยตรง_"
        )
        return embed

    return discord.Embed(title=f"หน้า {page}", color=color)


# ============================================================
# VIEW
# ============================================================

class ConfigView(discord.ui.View):
    """Unified config panel — 10 pages, always edit_message on navigation."""

    def __init__(self, page: int = 1, author_id: int = 0):
        super().__init__(timeout=300)
        self.page      = page
        self.author_id = author_id
        self._build()

    # ── public embed method ──────────────────────────────────
    def _page_embed(self) -> discord.Embed:
        return _build_page_embed(self.page)

    # ── rebuild items for current page ──────────────────────
    def _build(self):
        self.clear_items()
        p = self.page

        # ── Row 0: navigation ──
        prev_btn = discord.ui.Button(
            label="◀",
            style=discord.ButtonStyle.secondary,
            disabled=(p == 1),
            row=0,
            custom_id="cfg_prev",
        )
        prev_btn.callback = self._cb_prev
        self.add_item(prev_btn)

        page_ind = discord.ui.Button(
            label=f"หน้า {p}/{_TOTAL_PAGES}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
            row=0,
            custom_id="cfg_page_ind",
        )
        self.add_item(page_ind)

        next_btn = discord.ui.Button(
            label="▶",
            style=discord.ButtonStyle.secondary,
            disabled=(p == _TOTAL_PAGES),
            row=0,
            custom_id="cfg_next",
        )
        next_btn.callback = self._cb_next
        self.add_item(next_btn)

        # ── Page-specific controls ──
        if p == 1:
            self._build_page1()
        elif p == 2:
            self._build_page2()
        elif p == 3:
            self._build_page3()
        elif p == 4:
            self._build_page4()
        elif p == 5:
            pass   # page 5: no edit controls
        elif p == 6:
            self._build_page6()
        elif p == 7:
            pass   # page 7: no edit controls
        elif p == 8:
            self._build_page8()
        elif p == 9:
            self._build_page9()
        elif p == 10:
            self._build_page10()

        # ── Row 4: close ──
        close_btn = discord.ui.Button(
            label="❌ ปิด",
            style=discord.ButtonStyle.danger,
            row=4,
            custom_id="cfg_close",
        )
        close_btn.callback = self._cb_close
        self.add_item(close_btn)

    # ── navigation callbacks ────────────────────────────────
    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if self.author_id and ix.user.id != self.author_id:
            await ix.response.send_message("❌ เมนูนี้ไม่ใช่ของคุณ", ephemeral=True)
            return False
        return True

    async def _cb_prev(self, ix: discord.Interaction):
        self.page = max(1, self.page - 1)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_next(self, ix: discord.Interaction):
        self.page = min(_TOTAL_PAGES, self.page + 1)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_close(self, ix: discord.Interaction):
        await ix.response.edit_message(
            content="✅ ปิดหน้าต่างตั้งค่าแล้ว",
            embed=None,
            view=None,
        )

    # ===========================================================
    # PAGE 1 — General
    # ===========================================================
    def _build_page1(self):
        # Edit currency button (row 1)
        edit_currency_btn = discord.ui.Button(
            label="✏️ แก้ไข Currency & เงินเริ่มต้น",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="cfg_p1_currency",
        )
        edit_currency_btn.callback = self._cb_p1_currency
        self.add_item(edit_currency_btn)

        # Toggle language button (row 1)
        cfg  = load_currency_cfg()
        lang = cfg.get("language", "th")
        lbl  = "🇬🇧 เปลี่ยนเป็น English" if lang == "th" else "🇹🇭 เปลี่ยนเป็น Thai"
        toggle_lang_btn = discord.ui.Button(
            label=lbl,
            style=discord.ButtonStyle.secondary,
            row=1,
            custom_id="cfg_p1_lang",
        )
        toggle_lang_btn.callback = self._cb_p1_lang
        self.add_item(toggle_lang_btn)

    async def _cb_p1_currency(self, ix: discord.Interaction):
        await ix.response.send_modal(_CurrencyModal(self))

    async def _cb_p1_lang(self, ix: discord.Interaction):
        cfg  = load_currency_cfg()
        lang = cfg.get("language", "th")
        cfg["language"] = "en" if lang == "th" else "th"
        save_currency_cfg(cfg)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    # ===========================================================
    # PAGE 2 — Channels
    # ===========================================================
    def _build_page2(self):
        # Mission board channel add (row 1)
        add_board_sel = discord.ui.ChannelSelect(
            placeholder="➕ เพิ่ม Mission Board Channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=5,
            row=1,
            custom_id="cfg_p2_add_board",
        )
        add_board_sel.callback = self._cb_p2_add_board
        self.add_item(add_board_sel)

        # Clear board channels button (row 2)
        clr_board_btn = discord.ui.Button(
            label="🗑️ ล้าง Board Channels",
            style=discord.ButtonStyle.danger,
            row=2,
            custom_id="cfg_p2_clr_board",
        )
        clr_board_btn.callback = self._cb_p2_clr_board
        self.add_item(clr_board_btn)

        # Review channel select (row 3)
        review_sel = discord.ui.ChannelSelect(
            placeholder="📋 เปลี่ยน Admin Review Channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=3,
            custom_id="cfg_p2_review_ch",
        )
        review_sel.callback = self._cb_p2_review_ch
        self.add_item(review_sel)

        # Registration role select (row 2)
        reg_role_sel = discord.ui.RoleSelect(
            placeholder="🎭 เปลี่ยน Registration Role",
            min_values=1,
            max_values=1,
            row=2,
            custom_id="cfg_p2_reg_role",
        )
        reg_role_sel.callback = self._cb_p2_reg_role
        self.add_item(reg_role_sel)

    async def _cb_p2_add_board(self, ix: discord.Interaction):
        mc  = _load_missions_cfg()
        ids = mc.get("board_channel_ids", [])
        for ch in ix.data.get("resolved", {}).get("channels", {}).values():
            cid = int(ch["id"])
            if cid not in ids:
                ids.append(cid)
        mc["board_channel_ids"] = ids
        _save_missions_cfg(mc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p2_clr_board(self, ix: discord.Interaction):
        mc = _load_missions_cfg()
        mc["board_channel_ids"] = []
        _save_missions_cfg(mc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p2_review_ch(self, ix: discord.Interaction):
        chs = ix.data.get("resolved", {}).get("channels", {})
        if chs:
            cid = int(next(iter(chs)))
            cc  = _load_creation_cfg()
            cc["review_channel_id"] = cid
            _save_creation_cfg(cc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p2_reg_role(self, ix: discord.Interaction):
        roles = ix.data.get("resolved", {}).get("roles", {})
        if roles:
            rid = int(next(iter(roles)))
            cc  = _load_creation_cfg()
            cc["registration_role_id"] = rid
            _save_creation_cfg(cc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    # ===========================================================
    # PAGE 3 — Character Creation
    # ===========================================================
    def _build_page3(self):
        # Forum channel ID via modal (row 1)
        forum_btn = discord.ui.Button(
            label="🗂️ ตั้ง Forum Channel ID",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="cfg_p3_forum",
        )
        forum_btn.callback = self._cb_p3_forum
        self.add_item(forum_btn)

        # Admin role for reviewing — RoleSelect (row 2)
        admin_role_sel = discord.ui.RoleSelect(
            placeholder="🛡️ เพิ่ม/เปลี่ยน Admin Review Roles",
            min_values=1,
            max_values=5,
            row=2,
            custom_id="cfg_p3_admin_roles",
        )
        admin_role_sel.callback = self._cb_p3_admin_roles
        self.add_item(admin_role_sel)

        # Auto-assign role on approve — RoleSelect (row 3)
        auto_role_sel = discord.ui.RoleSelect(
            placeholder="✅ Auto-assign Role เมื่อ Approve",
            min_values=1,
            max_values=1,
            row=3,
            custom_id="cfg_p3_auto_role",
        )
        auto_role_sel.callback = self._cb_p3_auto_role
        self.add_item(auto_role_sel)

    async def _cb_p3_forum(self, ix: discord.Interaction):
        await ix.response.send_modal(_ForumChannelModal(self))

    async def _cb_p3_admin_roles(self, ix: discord.Interaction):
        roles = ix.data.get("resolved", {}).get("roles", {})
        if roles:
            cc = _load_creation_cfg()
            new_ids = [int(rid) for rid in roles]
            existing = cc.get("admin_role_ids", [])
            for rid in new_ids:
                if rid not in existing:
                    existing.append(rid)
            cc["admin_role_ids"] = existing
            _save_creation_cfg(cc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p3_auto_role(self, ix: discord.Interaction):
        roles = ix.data.get("resolved", {}).get("roles", {})
        if roles:
            rid = int(next(iter(roles)))
            cc  = _load_creation_cfg()
            cc["auto_assign_role_id"] = rid
            _save_creation_cfg(cc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    # ===========================================================
    # PAGE 4 — Stats Training
    # ===========================================================
    def _build_page4(self):
        # Rank cap button (row 1)
        rank_btn = discord.ui.Button(
            label="🏆 แก้ Rank Cap",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="cfg_p4_rank_cap",
        )
        rank_btn.callback = self._cb_p4_rank_cap
        self.add_item(rank_btn)

        # Training cost + cooldown button (row 1)
        cost_btn = discord.ui.Button(
            label="💰 แก้ Cost & Cooldown",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="cfg_p4_cost_cd",
        )
        cost_btn.callback = self._cb_p4_cost_cd
        self.add_item(cost_btn)

        # Exceed-cap roles — RoleSelect add (row 2)
        exceed_add_sel = discord.ui.RoleSelect(
            placeholder="➕ เพิ่ม Exceed-cap Role",
            min_values=1,
            max_values=5,
            row=2,
            custom_id="cfg_p4_exceed_add",
        )
        exceed_add_sel.callback = self._cb_p4_exceed_add
        self.add_item(exceed_add_sel)

        # Exceed-cap roles — clear button (row 3)
        exceed_clr_btn = discord.ui.Button(
            label="🗑️ ล้าง Exceed-cap Roles",
            style=discord.ButtonStyle.danger,
            row=3,
            custom_id="cfg_p4_exceed_clr",
        )
        exceed_clr_btn.callback = self._cb_p4_exceed_clr
        self.add_item(exceed_clr_btn)

    async def _cb_p4_rank_cap(self, ix: discord.Interaction):
        await ix.response.send_modal(_RankCapModal(self))

    async def _cb_p4_cost_cd(self, ix: discord.Interaction):
        await ix.response.send_modal(_TrainingCostModal(self))

    async def _cb_p4_exceed_add(self, ix: discord.Interaction):
        roles = ix.data.get("resolved", {}).get("roles", {})
        if roles:
            sc  = _load_stats_cfg()
            ids = sc.get("exceed_cap_role_ids", [])
            for rid in roles:
                r = int(rid)
                if r not in ids:
                    ids.append(r)
            sc["exceed_cap_role_ids"] = ids
            _save_stats_cfg(sc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p4_exceed_clr(self, ix: discord.Interaction):
        sc = _load_stats_cfg()
        sc["exceed_cap_role_ids"] = []
        _save_stats_cfg(sc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    # ===========================================================
    # PAGE 6 — Scavenge
    # ===========================================================
    def _build_page6(self):
        cd_btn = discord.ui.Button(
            label="⏱️ แก้ Cooldown /คลังไอเทม",
            style=discord.ButtonStyle.primary,
            row=1,
            custom_id="cfg_p6_cd",
        )
        cd_btn.callback = self._cb_p6_cd
        self.add_item(cd_btn)

    async def _cb_p6_cd(self, ix: discord.Interaction):
        await ix.response.send_modal(_ScavengeCooldownModal(self))

    # ===========================================================
    # PAGE 8 — Creation System
    # ===========================================================
    def _build_page8(self):
        # Creation roles — RoleSelect add/remove (row 1)
        creation_role_sel = discord.ui.RoleSelect(
            placeholder="🔨 เพิ่ม Blacksmith/Creation Roles",
            min_values=1,
            max_values=5,
            row=1,
            custom_id="cfg_p8_creation_roles",
        )
        creation_role_sel.callback = self._cb_p8_creation_roles
        self.add_item(creation_role_sel)

        # Clear creation roles (row 2)
        clr_creation_btn = discord.ui.Button(
            label="🗑️ ล้าง Creation Roles",
            style=discord.ButtonStyle.danger,
            row=2,
            custom_id="cfg_p8_clr_creation",
        )
        clr_creation_btn.callback = self._cb_p8_clr_creation
        self.add_item(clr_creation_btn)

        # Review channel — ChannelSelect (row 3)
        review_ch_sel = discord.ui.ChannelSelect(
            placeholder="📋 เปลี่ยน Review Channel",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=3,
            custom_id="cfg_p8_review_ch",
        )
        review_ch_sel.callback = self._cb_p8_review_ch
        self.add_item(review_ch_sel)

    async def _cb_p8_creation_roles(self, ix: discord.Interaction):
        roles = ix.data.get("resolved", {}).get("roles", {})
        if roles:
            cc  = _load_creation_cfg()
            ids = cc.get("creation_role_ids", [])
            for rid in roles:
                r = int(rid)
                if r not in ids:
                    ids.append(r)
            cc["creation_role_ids"] = ids
            _save_creation_cfg(cc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p8_clr_creation(self, ix: discord.Interaction):
        cc = _load_creation_cfg()
        cc["creation_role_ids"] = []
        _save_creation_cfg(cc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p8_review_ch(self, ix: discord.Interaction):
        chs = ix.data.get("resolved", {}).get("channels", {})
        if chs:
            cid = int(next(iter(chs)))
            cc  = _load_creation_cfg()
            cc["review_channel_id"] = cid
            _save_creation_cfg(cc)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)


    # ===========================================================
    # PAGE 9 — Character Options (race/gender/occupation + approved roles)
    # ===========================================================
    def _build_page9(self):
        # Add Race button (row 1)
        add_race_btn = discord.ui.Button(label="➕ เพิ่ม Race", style=discord.ButtonStyle.success, row=1, custom_id="cfg_p9_add_race")
        add_race_btn.callback = self._cb_p9_add_race
        self.add_item(add_race_btn)

        rm_race_btn = discord.ui.Button(label="➖ ลบ Race", style=discord.ButtonStyle.danger, row=1, custom_id="cfg_p9_rm_race")
        rm_race_btn.callback = self._cb_p9_rm_race
        self.add_item(rm_race_btn)

        # Add Occupation (row 2)
        add_occ_btn = discord.ui.Button(label="➕ เพิ่ม Occupation", style=discord.ButtonStyle.success, row=2, custom_id="cfg_p9_add_occ")
        add_occ_btn.callback = self._cb_p9_add_occ
        self.add_item(add_occ_btn)

        rm_occ_btn = discord.ui.Button(label="➖ ลบ Occupation", style=discord.ButtonStyle.danger, row=2, custom_id="cfg_p9_rm_occ")
        rm_occ_btn.callback = self._cb_p9_rm_occ
        self.add_item(rm_occ_btn)

        # Gender options (row 3)
        gender_btn = discord.ui.Button(label="⚙️ ตั้ง Gender Options", style=discord.ButtonStyle.primary, row=3, custom_id="cfg_p9_gender")
        gender_btn.callback = self._cb_p9_gender
        self.add_item(gender_btn)

        # Approved roles RoleSelect (row 4) — already occupies close button's row, so put select here
        approved_btn = discord.ui.Button(label="🎭 Approved Roles", style=discord.ButtonStyle.primary, row=3, custom_id="cfg_p9_approved")
        approved_btn.callback = self._cb_p9_approved
        self.add_item(approved_btn)

    async def _cb_p9_add_race(self, ix: discord.Interaction):
        await ix.response.send_modal(_AddOptionModal(self, "race", "Race"))

    async def _cb_p9_rm_race(self, ix: discord.Interaction):
        opts = _load_char_options_cfg()
        races = opts.get("races", [])
        if not races:
            await ix.response.send_message("❌ ยังไม่มี Race ที่จะลบ", ephemeral=True); return
        await ix.response.send_message(
            "เลือก Race ที่จะลบ:", view=_RemoveOptionView(self, "race", races), ephemeral=True,
        )

    async def _cb_p9_add_occ(self, ix: discord.Interaction):
        await ix.response.send_modal(_AddOptionModal(self, "occupation", "Occupation/ชั้น"))

    async def _cb_p9_rm_occ(self, ix: discord.Interaction):
        opts = _load_char_options_cfg()
        occs = opts.get("occupations", [])
        if not occs:
            await ix.response.send_message("❌ ยังไม่มี Occupation ที่จะลบ", ephemeral=True); return
        await ix.response.send_message(
            "เลือก Occupation ที่จะลบ:", view=_RemoveOptionView(self, "occupation", occs), ephemeral=True,
        )

    async def _cb_p9_gender(self, ix: discord.Interaction):
        await ix.response.send_modal(_GenderOptionsModal(self))

    async def _cb_p9_approved(self, ix: discord.Interaction):
        await ix.response.send_message(
            "เลือก Role ที่ผู้เล่นได้รับเมื่อ Approve ตัวละคร (เลือกได้หลาย Role):",
            view=_ApprovedRolesView(self),
            ephemeral=True,
        )

    # ===========================================================
    # PAGE 10 — Logs
    # ===========================================================
    def _build_page10(self):
        log_ch_sel = discord.ui.ChannelSelect(
            placeholder="📋 เลือกช่อง Log...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=1,
        )
        log_ch_sel.callback = self._cb_p10_log_ch
        self.add_item(log_ch_sel)

        log_cfg = _load_log_cfg()
        enabled = log_cfg.get("enabled", True)
        toggle_btn = discord.ui.Button(
            label="🔴 ปิด Log" if enabled else "🟢 เปิด Log",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id="cfg_p10_toggle",
        )
        toggle_btn.callback = self._cb_p10_toggle
        self.add_item(toggle_btn)

        clr_btn = discord.ui.Button(label="🗑️ ล้างช่อง Log", style=discord.ButtonStyle.danger, row=2, custom_id="cfg_p10_clr")
        clr_btn.callback = self._cb_p10_clr
        self.add_item(clr_btn)

    async def _cb_p10_log_ch(self, ix: discord.Interaction):
        ch = ix.data["values"][0] if ix.data.get("values") else None
        if not ch:
            await ix.response.defer(); return
        ch_id = int(ch)
        cfg = _load_log_cfg()
        cfg["log_channel_id"] = ch_id
        _save_log_cfg(cfg)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p10_toggle(self, ix: discord.Interaction):
        cfg = _load_log_cfg()
        cfg["enabled"] = not cfg.get("enabled", True)
        _save_log_cfg(cfg)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)

    async def _cb_p10_clr(self, ix: discord.Interaction):
        cfg = _load_log_cfg()
        cfg["log_channel_id"] = None
        _save_log_cfg(cfg)
        self._build()
        await ix.response.edit_message(embed=self._page_embed(), view=self)


# ============================================================
# HELPER MODALS & VIEWS for Page 9
# ============================================================

class _AddOptionModal(discord.ui.Modal):
    f_label  = discord.ui.TextInput(label="ชื่อ", max_length=60)
    f_role_id = discord.ui.TextInput(label="Role ID (ว่างได้)", required=False, max_length=20, placeholder="กรอก ID ยศ Discord หรือว่าง")

    def __init__(self, parent_cfg_view, option_key: str, display_name: str):
        super().__init__(title=f"➕ เพิ่ม {display_name}")
        self.parent  = parent_cfg_view
        self.option_key = option_key

    async def on_submit(self, ix: discord.Interaction):
        label   = self.f_label.value.strip()
        role_id = (self.f_role_id.value or "").strip() or None
        if role_id:
            try: role_id = str(int(role_id))
            except ValueError: role_id = None
        opts = _load_char_options_cfg()
        key  = self.option_key + "s"  # races / occupations
        opts.setdefault(key, [])
        if not any(o.get("label") == label for o in opts[key]):
            opts[key].append({"label": label, "role_id": role_id})
        _save_char_options_cfg(opts)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _RemoveOptionSelect(discord.ui.Select):
    def __init__(self, parent_cfg_view, option_key: str, items: list):
        self.parent = parent_cfg_view
        self.option_key = option_key
        opts = [discord.SelectOption(label=o["label"][:100], value=o["label"]) for o in items[:25]]
        super().__init__(placeholder="เลือกตัวเลือกที่จะลบ...", options=opts)

    async def callback(self, ix: discord.Interaction):
        label = self.values[0]
        opts  = _load_char_options_cfg()
        key   = self.option_key + "s"
        opts[key] = [o for o in opts.get(key, []) if o.get("label") != label]
        _save_char_options_cfg(opts)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _RemoveOptionView(discord.ui.View):
    def __init__(self, parent_cfg_view, option_key: str, items: list):
        super().__init__(timeout=120)
        self.add_item(_RemoveOptionSelect(parent_cfg_view, option_key, items))


class _GenderOptionsModal(discord.ui.Modal, title="⚙️ ตั้ง Gender Options"):
    f_list = discord.ui.TextInput(
        label="รายชื่อเพศ (คั่นด้วย , หรือขึ้นบรรทัดใหม่)",
        style=discord.TextStyle.paragraph,
        placeholder="ชาย\nหญิง\nไม่ระบุ",
        max_length=500,
    )

    def __init__(self, parent_cfg_view):
        super().__init__()
        self.parent = parent_cfg_view
        opts = _load_char_options_cfg()
        current = ", ".join(o.get("label","") for o in opts.get("genders", []))
        self.f_list.default = current

    async def on_submit(self, ix: discord.Interaction):
        raw   = self.f_list.value
        labels = [l.strip() for l in raw.replace(",", "\n").splitlines() if l.strip()]
        opts  = _load_char_options_cfg()
        existing = {o["label"]: o.get("role_id") for o in opts.get("genders", [])}
        opts["genders"] = [{"label": l, "role_id": existing.get(l)} for l in labels]
        _save_char_options_cfg(opts)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _ApprovedRolesSelect(discord.ui.RoleSelect):
    def __init__(self, parent_cfg_view):
        self.parent = parent_cfg_view
        super().__init__(placeholder="🎭 เลือก Role ที่ได้รับเมื่อ Approve...", min_values=1, max_values=10)

    async def callback(self, ix: discord.Interaction):
        role_ids = [str(r.id) for r in self.values]
        opts = _load_char_options_cfg()
        opts["approved_role_ids"] = list(set(opts.get("approved_role_ids", []) + role_ids))
        _save_char_options_cfg(opts)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _ClearApprovedBtn(discord.ui.Button):
    def __init__(self, parent_cfg_view):
        super().__init__(label="🗑️ ล้าง Approved Roles", style=discord.ButtonStyle.danger)
        self.parent = parent_cfg_view

    async def callback(self, ix: discord.Interaction):
        opts = _load_char_options_cfg()
        opts["approved_role_ids"] = []
        _save_char_options_cfg(opts)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._page_embed(), view=self.parent)


class _ApprovedRolesView(discord.ui.View):
    def __init__(self, parent_cfg_view):
        super().__init__(timeout=180)
        self.add_item(_ApprovedRolesSelect(parent_cfg_view))
        self.add_item(_ClearApprovedBtn(parent_cfg_view))


# ============================================================
# ADMIN CHECK
# ============================================================

def _is_admin(ix: discord.Interaction) -> bool:
    if not ix.guild:
        return False
    m = ix.guild.get_member(ix.user.id)
    return m is not None and (
        m.guild_permissions.administrator or m.guild_permissions.manage_guild
    )


# ============================================================
# SLASH COMMAND
# ============================================================

@bot.tree.command(
    name="config",
    description="[Admin] ตั้งค่าทั้งหมดของบอท Orion",
    guild=_ORION_GUILD_OBJ,
)
async def cmd_config(ix: discord.Interaction):
    if not _is_admin(ix):
        await ix.response.send_message(
            "❌ คำสั่งนี้ใช้ได้เฉพาะ Admin เท่านั้น", ephemeral=True
        )
        return
    view = ConfigView(page=1, author_id=ix.user.id)
    await ix.response.send_message(
        embed=view._page_embed(),
        view=view,
        ephemeral=True,
    )
