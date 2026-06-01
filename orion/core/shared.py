"""Shared utilities for the Orion bot — data helpers, rank system, config."""
import os
import json
import time
import uuid
import contextvars
from pathlib import Path

# ── Guild IDs ─────────────────────────────────────────────────────────────────
ORION_GUILD_ID = 1498627055909339157
GUILD2_ID      = 1509774885310693480
ALLOWED_GUILD_IDS = {ORION_GUILD_ID, GUILD2_ID}

# discord.Object handles for command guild registration
import discord as _discord
GUILD_OBJECTS = [_discord.Object(id=ORION_GUILD_ID), _discord.Object(id=GUILD2_ID)]

# ── Per-guild context ─────────────────────────────────────────────────────────
_current_guild_id: contextvars.ContextVar[int] = contextvars.ContextVar(
    "orion_guild_id", default=ORION_GUILD_ID
)

def get_data_dir(gid: int | None = None) -> Path:
    gid = gid or _current_guild_id.get()
    if gid == ORION_GUILD_ID:
        return Path("data/orion")
    return Path(f"data/orion_g{gid}")

def ensure_dirs():
    for gid in ALLOWED_GUILD_IDS:
        get_data_dir(gid).mkdir(parents=True, exist_ok=True)

ensure_dirs()

# ── Rank system ───────────────────────────────────────────────────────────────
RANKS = [
    "E-", "E", "E+",
    "D-", "D", "D+",
    "C-", "C", "C+",
    "B-", "B", "B+",
    "A-", "A", "A+",
    "S-", "S", "S+",
    "EX",
]
ATTRIBUTES = ["endurance", "strength", "perception", "speed"]
ATTR_LABELS = {
    "endurance":  "ความอดทน",
    "strength":   "พละกำลัง",
    "perception": "การรับรู้",
    "speed":      "ความเร็ว",
}
XP_PER_RANK    = 100
DEFAULT_CAP    = "B+"
EMBED_COLOR    = 0x5865F2


def rank_index(r: str) -> int:
    try:
        return RANKS.index(r)
    except ValueError:
        return 0


def next_rank(r: str) -> str | None:
    idx = rank_index(r) + 1
    return RANKS[idx] if idx < len(RANKS) else None


def progress_bar(xp: int, width: int = 10) -> str:
    filled = min(width, int(xp / XP_PER_RANK * width))
    return "█" * filled + "░" * (width - filled)


def default_stats() -> dict:
    return {attr: {"rank": "E-", "xp": 0} for attr in ATTRIBUTES}


def overall_rank(stats: dict) -> str:
    """Return the lowest attribute rank (weakest link)."""
    if not stats:
        return "E-"
    idxs = [rank_index(stats[a]["rank"]) for a in ATTRIBUTES if a in stats]
    return RANKS[min(idxs)] if idxs else "E-"


def format_cooldown(seconds: int) -> str:
    if seconds <= 0:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


# ── JSON helpers ──────────────────────────────────────────────────────────────
def load_json(path: Path | str, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if default is not None else {}


def save_json(path: Path | str, data):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Per-guild data ─────────────────────────────────────────────────────────────
def load_players(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "players.json", {})


def save_players(gid: int, data: dict):
    save_json(get_data_dir(gid) / "players.json", data)


def load_config(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "config.json", {})


def save_config(gid: int, data: dict):
    save_json(get_data_dir(gid) / "config.json", data)


def load_pending(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "pending.json", {})


def save_pending(gid: int, data: dict):
    save_json(get_data_dir(gid) / "pending.json", data)


def load_missions(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "missions.json", {})


def save_missions(gid: int, data: dict):
    save_json(get_data_dir(gid) / "missions.json", data)


def load_shop(gid: int) -> dict:
    return load_json(
        get_data_dir(gid) / "shop.json",
        {"categories": {}, "items": {}},
    )


def save_shop(gid: int, data: dict):
    save_json(get_data_dir(gid) / "shop.json", data)


def load_items_catalog(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "items.json", {})


def save_items_catalog(gid: int, data: dict):
    save_json(get_data_dir(gid) / "items.json", data)


def load_skill_cats(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "skill_categories.json", {})


def save_skill_cats(gid: int, data: dict):
    save_json(get_data_dir(gid) / "skill_categories.json", data)


# ── Currency helpers ──────────────────────────────────────────────────────────
def currency_cfg(gid: int) -> dict:
    cfg = load_config(gid)
    return {
        "name":  cfg.get("currency_name", "Gold"),
        "emoji": cfg.get("currency_emoji", "💰"),
    }


def money_str(amount: int, gid: int) -> str:
    cc = currency_cfg(gid)
    return f"{cc['emoji']} {amount:,} {cc['name']}"


def get_wallet(gid: int, uid: int | str) -> int:
    return load_players(gid).get(str(uid), {}).get("balance", 0)


def add_money(gid: int, uid: int | str, delta: int) -> int:
    players = load_players(gid)
    key = str(uid)
    if key not in players:
        players[key] = {}
    players[key]["balance"] = max(0, players[key].get("balance", 0) + delta)
    save_players(gid, players)
    return players[key]["balance"]


# ── Cooldown helpers ──────────────────────────────────────────────────────────
def load_cooldowns(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "cooldowns.json", {})


def save_cooldowns(gid: int, data: dict):
    save_json(get_data_dir(gid) / "cooldowns.json", data)


def cooldown_remaining(gid: int, uid: int | str, key: str) -> int:
    cds = load_cooldowns(gid)
    exp = cds.get(str(uid), {}).get(key, 0)
    return max(0, int(exp - time.time()))


def set_cooldown(gid: int, uid: int | str, key: str, seconds: int):
    cds = load_cooldowns(gid)
    k = str(uid)
    if k not in cds:
        cds[k] = {}
    cds[k][key] = time.time() + seconds
    save_cooldowns(gid, cds)


def clear_cooldown(gid: int, uid: int | str, key: str):
    cds = load_cooldowns(gid)
    cds.get(str(uid), {}).pop(key, None)
    save_cooldowns(gid, cds)


# ── Minigames (shared implementations used by training/scavenge) ──────────────
import asyncio
import random


async def mg_guess_number(ix: discord.Interaction) -> bool:
    secret = random.randint(1, 10)
    embed = discord.Embed(
        title="🔢 ทายตัวเลข",
        description="ทายตัวเลข **1–10** ภายใน 20 วินาที!",
        color=EMBED_COLOR,
    )
    opts = [
        discord.SelectOption(label=str(n), value=str(n))
        for n in range(1, 11)
    ]
    sel = discord.ui.Select(placeholder="เลือกตัวเลข…", options=opts)
    view = discord.ui.View(timeout=20)
    view.add_item(sel)
    result: list[bool] = []

    async def cb(interaction: discord.Interaction):
        chosen = int(sel.values[0])
        won = chosen == secret
        result.append(won)
        color = discord.Color.green() if won else discord.Color.red()
        e = discord.Embed(
            description=f"{'✅ ถูก!' if won else f'❌ ผิด! เฉลย: **{secret}**'}",
            color=color,
        )
        await interaction.response.edit_message(embed=e, view=None)
        view.stop()

    sel.callback = cb
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()
    return bool(result and result[0])


async def mg_math_quick(ix: discord.Interaction) -> bool:
    a, b = random.randint(1, 20), random.randint(1, 20)
    ops = [("+", a + b), ("-", abs(a - b)), ("×", a * b)]
    op_sym, answer = random.choice(ops)
    wrong = {answer}
    choices = [answer]
    while len(choices) < 4:
        w = answer + random.randint(-5, 5)
        if w not in wrong and w >= 0:
            wrong.add(w)
            choices.append(w)
    random.shuffle(choices)
    embed = discord.Embed(
        title="➕ คำนวณเร็ว",
        description=f"**{a} {op_sym} {b} = ?**\nตอบภายใน 15 วินาที!",
        color=EMBED_COLOR,
    )
    opts = [discord.SelectOption(label=str(c), value=str(c)) for c in choices]
    sel = discord.ui.Select(placeholder="เลือกคำตอบ…", options=opts)
    view = discord.ui.View(timeout=15)
    view.add_item(sel)
    result: list[bool] = []

    async def cb(interaction: discord.Interaction):
        won = int(sel.values[0]) == answer
        result.append(won)
        e = discord.Embed(
            description=f"{'✅ ถูก!' if won else f'❌ ผิด! เฉลย: **{answer}**'}",
            color=discord.Color.green() if won else discord.Color.red(),
        )
        await interaction.response.edit_message(embed=e, view=None)
        view.stop()

    sel.callback = cb
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()
    return bool(result and result[0])


async def mg_click_target(ix: discord.Interaction) -> bool:
    correct_idx = random.randint(0, 3)
    view = discord.ui.View(timeout=10)
    result: list[bool] = []
    for i in range(4):
        is_target = i == correct_idx
        btn = discord.ui.Button(
            label="⚡ กด!" if is_target else "✗",
            style=discord.ButtonStyle.success if is_target else discord.ButtonStyle.secondary,
            row=0,
        )

        async def make_cb(won: bool):
            async def cb(interaction: discord.Interaction):
                result.append(won)
                e = discord.Embed(
                    description="✅ เร็วมาก!" if won else "❌ ผิดปุ่ม!",
                    color=discord.Color.green() if won else discord.Color.red(),
                )
                await interaction.response.edit_message(embed=e, view=None)
                view.stop()
            return cb

        btn.callback = await make_cb(is_target)
        view.add_item(btn)

    embed = discord.Embed(
        title="⚡ กดปุ่มให้ถูก!",
        description="กดปุ่ม **⚡ กด!** ภายใน 10 วินาที!",
        color=EMBED_COLOR,
    )
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()
    return bool(result and result[0])


async def mg_rps(ix: discord.Interaction) -> bool:
    rps = {"🪨 หิน": "✂️ กรรไกร", "📄 กระดาษ": "🪨 หิน", "✂️ กรรไกร": "📄 กระดาษ"}
    choices = list(rps.keys())
    bot_choice = random.choice(choices)
    view = discord.ui.View(timeout=15)
    result: list[bool] = []

    async def make_btn(label: str):
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)

        async def cb(interaction: discord.Interaction):
            player = label
            won = rps[player] == bot_choice
            draw = player == bot_choice
            if draw:
                won = False
                msg = f"🤝 เสมอ! บอท: **{bot_choice}**"
            else:
                msg = ("✅ ชนะ!" if won else "❌ แพ้!") + f" บอท: **{bot_choice}**"
            result.append(won)
            e = discord.Embed(
                description=msg,
                color=discord.Color.green() if won else discord.Color.red(),
            )
            await interaction.response.edit_message(embed=e, view=None)
            view.stop()

        btn.callback = cb
        return btn

    for c in choices:
        view.add_item(await make_btn(c))

    embed = discord.Embed(
        title="✊ เป่ายิ้งฉุบ",
        description="เลือก หิน กระดาษ หรือ กรรไกร!",
        color=EMBED_COLOR,
    )
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()
    return bool(result and result[0])


async def mg_odd_one_out(ix: discord.Interaction) -> bool:
    sets = [
        (["🍎", "🍊", "🍋", "🐶"], 3),
        (["🔵", "🔵", "🔵", "🔴"], 3),
        (["1", "2", "4", "3"], 2),
        (["🐱", "🐶", "🐭", "🌸"], 3),
        (["A", "B", "C", "1"], 3),
    ]
    items, odd_idx = random.choice(sets)
    view = discord.ui.View(timeout=15)
    result: list[bool] = []

    async def make_btn(label: str, idx: int):
        btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary)

        async def cb(interaction: discord.Interaction):
            won = idx == odd_idx
            result.append(won)
            e = discord.Embed(
                description="✅ ถูก! หาตัวผิดปกติได้!" if won else f"❌ ผิด! ตอบคือ **{items[odd_idx]}**",
                color=discord.Color.green() if won else discord.Color.red(),
            )
            await interaction.response.edit_message(embed=e, view=None)
            view.stop()

        btn.callback = cb
        return btn

    for i, item in enumerate(items):
        view.add_item(await make_btn(item, i))

    embed = discord.Embed(
        title="🔍 หาตัวที่ต่าง",
        description="เลือกสิ่งที่ **ไม่เข้าพวก**!",
        color=EMBED_COLOR,
    )
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
    await view.wait()
    return bool(result and result[0])


MINIGAME_KEYS = ["guess_number", "math_quick", "click_target", "rps", "odd_one_out"]
MINIGAME_LABELS = {
    "guess_number": "ทายตัวเลข",
    "math_quick":   "คำนวณเร็ว",
    "click_target": "กดปุ่มเร็ว",
    "rps":          "เป่ายิ้งฉุบ",
    "odd_one_out":  "หาตัวที่ต่าง",
}

_MINIGAME_FNS = {
    "guess_number": mg_guess_number,
    "math_quick":   mg_math_quick,
    "click_target": mg_click_target,
    "rps":          mg_rps,
    "odd_one_out":  mg_odd_one_out,
}


async def run_minigame(ix: discord.Interaction, key: str | None = None) -> bool:
    if key is None or key not in _MINIGAME_FNS:
        key = random.choice(MINIGAME_KEYS)
    return await _MINIGAME_FNS[key](ix)


# ── Bilingual translation system ──────────────────────────────────────────────

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # ── Missions ──────────────────────────────────────────────────────────
        "mission_new":          "⚔️ New Mission!",
        "mission_difficulty":   "Difficulty",
        "mission_reward":       "Reward",
        "mission_players":      "Players",
        "mission_description":  "Description",
        "mission_how_to_join":  "📌 How to Join",
        "mission_join_instr":   "1. Use `/missions` in this channel\n2. Select this mission from the list\n3. Click **✅ Join**",
        "mission_join_btn":     "✅ Join",
        "mission_leave_btn":    "❌ Leave",
        "mission_details_btn":  "📋 Details",
        "mission_full":         "This mission is full.",
        "mission_already_in":   "You have already joined this mission.",
        "mission_joined":       "✅ You joined **{title}**!",
        "mission_left":         "✅ You left **{title}**.",
        "mission_not_in":       "You are not in this mission.",
        "mission_closed":       "This mission is no longer open.",
        "mission_board_title":  "⚔️ Mission Board",
        "mission_board_empty":  "No open missions right now.",
        "mission_footer":       "Page {page}/{total}  ·  {count} open missions",
        "mission_open":         "Open",
        "mission_completed":    "Completed",
        "mission_unlimited":    "∞",
        "mission_no_char":      "You must create a character first. Use `/orion`.",
        # ── Shop ──────────────────────────────────────────────────────────────
        "shop_title":           "🏪 Shop",
        "shop_empty":           "No items available.",
        "shop_no_cats":         "No categories yet.",
        # ── Economy ───────────────────────────────────────────────────────────
        "wallet_title":         "💰 Wallet",
        "transfer_confirm":     "Transfer **{amount}** to **{target}**?",
        "transfer_no_funds":    "Insufficient funds.",
        "transfer_self":        "You cannot transfer to yourself.",
        # ── General ───────────────────────────────────────────────────────────
        "confirm_btn":          "✅ Confirm",
        "cancel_btn":           "❌ Cancel",
        "back_btn":             "◀ Back",
        "next_btn":             "Next ▶",
        "prev_btn":             "◀ Prev",
        "admin_only":           "Admin only.",
        "no_character":         "You don't have a character yet. Use `/orion`.",
        "done":                 "Done",
        "saved":                "✅ Saved.",
        "invalid_number":       "Invalid number.",
    },
    "th": {
        # ── Missions ──────────────────────────────────────────────────────────
        "mission_new":          "⚔️ ภารกิจใหม่!",
        "mission_difficulty":   "ความยาก",
        "mission_reward":       "รางวัล",
        "mission_players":      "ผู้เล่น",
        "mission_description":  "รายละเอียด",
        "mission_how_to_join":  "📌 วิธีเข้าร่วม",
        "mission_join_instr":   "1. ใช้คำสั่ง `/missions` ในห้องนี้\n2. เลือกภารกิจนี้จากรายการ\n3. กดปุ่ม **✅ เข้าร่วม**",
        "mission_join_btn":     "✅ เข้าร่วม",
        "mission_leave_btn":    "❌ ออก",
        "mission_details_btn":  "📋 รายละเอียด",
        "mission_full":         "ภารกิจเต็มแล้ว ไม่สามารถเข้าร่วมได้",
        "mission_already_in":   "คุณเข้าร่วมภารกิจนี้อยู่แล้ว",
        "mission_joined":       "✅ เข้าร่วม **{title}** แล้ว!",
        "mission_left":         "✅ ออกจาก **{title}** แล้ว",
        "mission_not_in":       "คุณไม่ได้อยู่ในภารกิจนี้",
        "mission_closed":       "ภารกิจนี้ปิดแล้ว",
        "mission_board_title":  "⚔️ กระดานภารกิจ",
        "mission_board_empty":  "ไม่มีภารกิจที่เปิดอยู่ในขณะนี้",
        "mission_footer":       "หน้า {page}/{total}  ·  {count} ภารกิจที่เปิด",
        "mission_open":         "เปิด",
        "mission_completed":    "เสร็จสิ้น",
        "mission_unlimited":    "∞",
        "mission_no_char":      "ต้องสร้างตัวละครก่อน ใช้ `/orion`",
        # ── Shop ──────────────────────────────────────────────────────────────
        "shop_title":           "🏪 ร้านค้า",
        "shop_empty":           "ไม่มีสินค้า",
        "shop_no_cats":         "ยังไม่มีหมวดสินค้า",
        # ── Economy ───────────────────────────────────────────────────────────
        "wallet_title":         "💰 กระเป๋าเงิน",
        "transfer_confirm":     "โอน **{amount}** ให้ **{target}**?",
        "transfer_no_funds":    "เงินไม่พอ",
        "transfer_self":        "ไม่สามารถโอนให้ตัวเองได้",
        # ── General ───────────────────────────────────────────────────────────
        "confirm_btn":          "✅ ยืนยัน",
        "cancel_btn":           "❌ ยกเลิก",
        "back_btn":             "◀ กลับ",
        "next_btn":             "ถัดไป ▶",
        "prev_btn":             "◀ ก่อนหน้า",
        "admin_only":           "เฉพาะ Admin เท่านั้น",
        "no_character":         "ยังไม่มีตัวละคร ใช้ `/orion` เพื่อสร้าง",
        "done":                 "เสร็จสิ้น",
        "saved":                "✅ บันทึกแล้ว",
        "invalid_number":       "ตัวเลขไม่ถูกต้อง",
    },
}


def t_orion(gid: int, key: str, **kwargs) -> str:
    """Return the translated string for the guild's configured language."""
    cfg  = load_config(gid)
    lang = cfg.get("language", "th")
    strings = _STRINGS.get(lang) or _STRINGS["th"]
    s = strings.get(key) or _STRINGS["th"].get(key, key)
    if kwargs:
        try:
            s = s.format(**kwargs)
        except Exception:
            pass
    return s
