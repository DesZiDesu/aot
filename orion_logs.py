# ============================================================
# ORION — Log System (บันทึกการกระทำของผู้เล่น)
# ============================================================
# ส่ง embed ไปยังช่อง log ที่แอดมินกำหนดทุกครั้งที่เกิด action
#
# Commands:
#   /logsแอดมิน  — [Admin] ตั้งค่าช่อง log + เปิด/ปิด
#   /logtest     — [Admin] ทดสอบส่ง log
# ============================================================

import sys
import datetime
import discord
from discord import app_commands

# ── ดึง dependencies จาก orion_bot ผ่าน sys.modules ─────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_logs ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                       = _orion_bot_mod.bot
ORION_GUILD_ID            = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ          = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR            = _orion_bot_mod.ORION_DATA_DIR
load_json                 = _orion_bot_mod.load_json
save_json                 = _orion_bot_mod.save_json


# ============================================================
# CONFIG FILE
# ============================================================

LOG_CONFIG_FILE = f"{ORION_DATA_DIR}/logs_config.json"

_LOG_CONFIG_DEFAULTS = {
    "log_channel_id": None,
    "enabled": True,
}


def _load_log_cfg() -> dict:
    cfg = load_json(LOG_CONFIG_FILE, {})
    for k, v in _LOG_CONFIG_DEFAULTS.items():
        cfg.setdefault(k, v)
    return cfg


def _save_log_cfg(cfg: dict):
    save_json(LOG_CONFIG_FILE, cfg)


# ============================================================
# ACTION META
# ============================================================

# action -> (emoji, color_int, title_thai)
ACTION_META: dict = {
    "money_receive":        ("💰", 0x2ecc71, "ได้รับเงิน"),
    "money_spend":          ("💸", 0xe74c3c, "ใช้จ่ายเงิน"),
    "money_transfer_send":  ("🔄", 0x3498db, "โอนเงินออก"),
    "money_transfer_recv":  ("🔄", 0x9b59b6, "รับโอนเงิน"),
    "stat_rankup":          ("📊", 0xf39c12, "Rank สถิติขึ้น"),
    "craft":                ("🔨", 0xe67e22, "คราฟไอเทม"),
    "char_delete":          ("🗑️", 0xe74c3c, "ลบตัวละคร"),
    "char_approved":        ("✅", 0x27ae60, "ตัวละครผ่านการอนุมัติ"),
    "char_declined":        ("❌", 0xc0392b, "ตัวละครไม่ผ่าน"),
    "skill_create":         ("✨", 0x9b59b6, "สร้างสกิลใหม่"),
    "skill_transfer_send":  ("⚙️", 0x3498db, "โอนสกิลออก"),
    "skill_transfer_recv":  ("⚙️", 0x9b59b6, "รับสกิล"),
    "item_receive":         ("📦", 0x1abc9c, "ได้รับไอเทม"),
    "item_sell":            ("🎁", 0xf1c40f, "ขายไอเทม"),
    "item_discard":         ("🗑️", 0x7f8c8d, "ทิ้งไอเทม"),
    "mission_join":         ("🏹", 0x2980b9, "เข้าร่วมภารกิจ"),
    "mission_complete":     ("🏆", 0xf39c12, "สำเร็จภารกิจ"),
    "job_complete":         ("💼", 0x16a085, "ทำงานสำเร็จ"),
    "char_create_submit":   ("📬", 0x3498db, "ส่งใบสมัครตัวละคร"),
    "char_edit":            ("✏️", 0x95a5a6, "แก้ไขตัวละคร"),
    "wallet_adjust_admin":  ("🔧", 0xe74c3c, "Admin ปรับเงิน"),
    "item_give_admin":      ("🎁", 0xe74c3c, "Admin ให้ไอเทม"),
}

# kwarg key -> Thai label
_KWARG_LABELS: dict = {
    "amount":    "จำนวน",
    "source":    "แหล่งที่มา",
    "to_uid":    "ผู้รับ",
    "from_uid":  "ผู้ส่ง",
    "item":      "ไอเทม",
    "qty":       "จำนวนชิ้น",
    "skill":     "ชื่อสกิล",
    "category":  "หมวด",
    "old_rank":  "rank เดิม",
    "new_rank":  "rank ใหม่",
    "attr":      "สถิติ",
    "reason":    "เหตุผล",
    "char_name": "ชื่อตัวละคร",
    "job":       "ชื่องาน",
    "mission":   "ชื่อภารกิจ",
    "reward":    "รางวัล",
}

_DETAIL_EMOJI = "📌"


def _build_description(**kwargs) -> str:
    """แปลง kwargs เป็น description หลายบรรทัด"""
    lines = []
    for key, val in kwargs.items():
        label = _KWARG_LABELS.get(key, key)
        lines.append(f"{_DETAIL_EMOJI} {label}: {val}")
    return "\n".join(lines) if lines else "—"


# ============================================================
# CORE: log_action
# ============================================================

async def log_action(uid: str, action: str, **kwargs):
    """ส่ง embed ไปยังช่อง log ของ Orion Guild"""
    try:
        cfg = _load_log_cfg()
        if not cfg.get("enabled", True):
            return
        channel_id = cfg.get("log_channel_id")
        if not channel_id:
            return

        guild = bot.get_guild(ORION_GUILD_ID)
        if guild is None:
            return

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            return

        # Resolve member
        try:
            member = guild.get_member(int(uid))
        except (ValueError, TypeError):
            member = None

        # Display name & avatar
        if member is not None:
            display_name = member.display_name
            avatar_url = member.display_avatar.url
        else:
            display_name = f"User {uid}"
            avatar_url = None

        # Action meta
        meta = ACTION_META.get(action)
        if meta:
            emoji, color, title_thai = meta
        else:
            emoji, color, title_thai = ("🔔", 0x95a5a6, action)

        # Build embed
        description = _build_description(**kwargs)
        timestamp = datetime.datetime.now(datetime.timezone.utc)

        embed = discord.Embed(
            title=f"{emoji} {title_thai}",
            description=description,
            color=color,
            timestamp=timestamp,
        )
        embed.set_author(
            name=f"{display_name} (ID: {uid})",
            icon_url=avatar_url,
        )
        embed.set_footer(text="🔍 Orion Logs")

        await channel.send(embed=embed)

    except Exception:
        pass  # Never raise — silently swallow all errors


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
# ADMIN VIEW
# ============================================================

def _make_log_admin_embed() -> discord.Embed:
    cfg = _load_log_cfg()
    channel_id = cfg.get("log_channel_id")
    enabled = cfg.get("enabled", True)

    ch_display = f"<#{channel_id}>" if channel_id else "_ยังไม่ได้ตั้งค่า_"
    status_display = "🟢 เปิดใช้งาน" if enabled else "🔴 ปิดอยู่"

    embed = discord.Embed(
        title="🔍 Orion Logs — ตั้งค่า",
        color=0x5865f2,
    )
    embed.add_field(name="ช่อง Log", value=ch_display, inline=True)
    embed.add_field(name="สถานะ", value=status_display, inline=True)
    return embed


class LogAdminView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self._build()

    def _build(self):
        self.clear_items()
        cfg = _load_log_cfg()
        enabled = cfg.get("enabled", True)

        # Row 0: ChannelSelect — text channels only
        ch_sel = discord.ui.ChannelSelect(
            placeholder="📋 เลือกช่อง Logs...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=0,
            custom_id="logs_ch_sel",
        )
        ch_sel.callback = self._cb_channel_select
        self.add_item(ch_sel)

        # Row 1: toggle enable/disable
        if enabled:
            toggle_btn = discord.ui.Button(
                label="🔴 ปิด Log",
                style=discord.ButtonStyle.danger,
                row=1,
                custom_id="logs_toggle",
            )
        else:
            toggle_btn = discord.ui.Button(
                label="🟢 เปิด Log",
                style=discord.ButtonStyle.success,
                row=1,
                custom_id="logs_toggle",
            )
        toggle_btn.callback = self._cb_toggle
        self.add_item(toggle_btn)

        # Row 2: clear channel
        clear_btn = discord.ui.Button(
            label="🗑️ ล้างช่อง Log",
            style=discord.ButtonStyle.secondary,
            row=2,
            custom_id="logs_clear_ch",
        )
        clear_btn.callback = self._cb_clear_channel
        self.add_item(clear_btn)

        # Row 3: done / close
        done_btn = discord.ui.Button(
            label="Done",
            style=discord.ButtonStyle.primary,
            row=3,
            custom_id="logs_done",
        )
        done_btn.callback = self._cb_done
        self.add_item(done_btn)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.id != self.author_id:
            await ix.response.send_message("❌ ไม่ใช่เจ้าของเมนูนี้", ephemeral=True)
            return False
        return True

    async def _cb_channel_select(self, ix: discord.Interaction):
        ch = ix.data.get("values", [None])[0]
        if not ch:
            await ix.response.defer()
            return
        # ChannelSelect values are channel objects accessible via resolved
        resolved_channels = ix.data.get("resolved", {}).get("channels", {})
        if resolved_channels:
            cid = int(next(iter(resolved_channels)))
        else:
            try:
                cid = int(ch)
            except (ValueError, TypeError):
                await ix.response.defer()
                return
        cfg = _load_log_cfg()
        cfg["log_channel_id"] = cid
        _save_log_cfg(cfg)
        self._build()
        await ix.response.edit_message(embed=_make_log_admin_embed(), view=self)

    async def _cb_toggle(self, ix: discord.Interaction):
        cfg = _load_log_cfg()
        cfg["enabled"] = not cfg.get("enabled", True)
        _save_log_cfg(cfg)
        self._build()
        await ix.response.edit_message(embed=_make_log_admin_embed(), view=self)

    async def _cb_clear_channel(self, ix: discord.Interaction):
        cfg = _load_log_cfg()
        cfg["log_channel_id"] = None
        _save_log_cfg(cfg)
        self._build()
        await ix.response.edit_message(embed=_make_log_admin_embed(), view=self)

    async def _cb_done(self, ix: discord.Interaction):
        await ix.response.edit_message(view=None)


# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(
    name="logsแอดมิน",
    description="[Admin] ตั้งค่าระบบ Log ของ Orion",
    guild=_ORION_GUILD_OBJ,
)
async def cmd_logs_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message(
            "❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True
        )
        return
    if not _is_admin(interaction):
        await interaction.response.send_message(
            "❌ คำสั่งนี้ใช้ได้เฉพาะ Admin เท่านั้น", ephemeral=True
        )
        return
    view = LogAdminView(author_id=interaction.user.id)
    await interaction.response.send_message(
        embed=_make_log_admin_embed(),
        view=view,
        ephemeral=True,
    )


@bot.tree.command(
    name="logtest",
    description="[Admin] ทดสอบส่ง log ตัวอย่าง",
    guild=_ORION_GUILD_OBJ,
)
async def cmd_log_test(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message(
            "❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True
        )
        return
    if not _is_admin(interaction):
        await interaction.response.send_message(
            "❌ คำสั่งนี้ใช้ได้เฉพาะ Admin เท่านั้น", ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    await log_action(
        str(interaction.user.id),
        "money_receive",
        amount=999,
        source="Test",
    )
    await interaction.followup.send("✅ ส่ง log ทดสอบแล้ว", ephemeral=True)
