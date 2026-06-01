# ============================================================
# ORION — Stats / Attributes Progression System
# ============================================================
# ผู้เล่นฝึก 4 attribute: Strength, Endurance, Speed, Perception
# แต่ละ attribute มี rank ตั้งแต่ E- ถึง EX (19 ระดับ)
# ใช้ /ฝึกสถิติ → เลือก attribute → ทำมินิเกม → ได้ XP → rank up
# ============================================================

import sys
import time
import random
import asyncio

import discord

# ── dependencies ──────────────────────────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_stats ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                       = _orion_bot_mod.bot
ORION_GUILD_ID            = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ          = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR            = _orion_bot_mod.ORION_DATA_DIR
load_json                 = _orion_bot_mod.load_json
save_json                 = _orion_bot_mod.save_json
ensure_orion_player       = _orion_bot_mod.ensure_orion_player
load_orion_players        = _orion_bot_mod.load_orion_players
save_orion_players        = _orion_bot_mod.save_orion_players
add_money                 = _orion_bot_mod.add_money
money_str                 = _orion_bot_mod.money_str

# ── Constants ─────────────────────────────────────────────────
RANKS = [
    "E-", "E", "E+",
    "D-", "D", "D+",
    "C-", "C", "C+",
    "B-", "B", "B+",
    "A-", "A", "A+",
    "S-", "S", "S+",
    "EX",
]
XP_PER_RANK  = 100
DEFAULT_CAP  = "B+"   # index 11
MAX_RANK_IDX = len(RANKS) - 1  # 18

ATTRS = [
    {"key": "strength",   "label": "Strength",   "emoji": "⚔️"},
    {"key": "endurance",  "label": "Endurance",  "emoji": "🛡️"},
    {"key": "speed",      "label": "Speed",      "emoji": "💨"},
    {"key": "perception", "label": "Perception", "emoji": "👁️"},
]

STATS_CONFIG_FILE = f"{ORION_DATA_DIR}/stats_config.json"

# ── Training word list for _mg_type_word ─────────────────────
_WORDS_5 = [
    "BRAVE", "SWIFT", "SHARP", "FLAME", "STORM",
    "FROST", "FORGE", "BLADE", "GUARD", "LIGHT",
    "CLOAK", "SPEAR", "MAGIC", "STEEL", "GRACE",
    "SCOUT", "TRAIL", "MIGHT", "CREST", "HONOR",
]


# ============================================================
# Config helpers
# ============================================================

def load_stats_config() -> dict:
    cfg = load_json(STATS_CONFIG_FILE, {})
    changed = False
    for k, v in [
        ("rank_cap",           DEFAULT_CAP),
        ("training_cost",      50),
        ("cooldown_seconds",   3600),
        ("exceed_cap_role_ids", []),
        ("exp_gain_min",       20),   # min XP per training
        ("exp_gain_max",       50),   # max XP per training
        ("exp_boosts",         {}),   # {uid: {"multiplier": float, "expires_at": float or 0}}
    ]:
        if k not in cfg:
            cfg[k] = v
            changed = True
    if changed:
        save_json(STATS_CONFIG_FILE, cfg)
    return cfg


def save_stats_config(cfg: dict):
    save_json(STATS_CONFIG_FILE, cfg)


# ============================================================
# Player stats helpers
# ============================================================

_ATTR_KEYS = [a["key"] for a in ATTRS]

_DEFAULT_ATTR_ENTRY = {"xp": 0, "rank_idx": 0}


def _ensure_attrs(player: dict):
    """Mutate player dict in-place to guarantee attrs + training_cooldown fields."""
    if "attrs" not in player:
        player["attrs"] = {}
    for key in _ATTR_KEYS:
        if key not in player["attrs"]:
            player["attrs"][key] = dict(_DEFAULT_ATTR_ENTRY)
    if "training_cooldown" not in player:
        player["training_cooldown"] = 0.0


def ensure_player_attrs(uid: str):
    ensure_orion_player(uid)
    data = load_orion_players()
    _ensure_attrs(data[uid])
    save_orion_players(data)


def _cap_for_player(uid: str) -> int:
    """Return effective rank index cap for this player."""
    cfg = load_stats_config()
    cap_str = cfg.get("rank_cap", DEFAULT_CAP)
    cap_idx = RANKS.index(cap_str) if cap_str in RANKS else RANKS.index(DEFAULT_CAP)

    exceed_role_ids = [int(r) for r in cfg.get("exceed_cap_role_ids", []) if str(r).isdigit()]
    if not exceed_role_ids:
        return cap_idx

    guild = bot.get_guild(ORION_GUILD_ID)
    if not guild:
        return cap_idx
    member = guild.get_member(int(uid))
    if not member:
        return cap_idx
    member_role_ids = {r.id for r in member.roles}
    if member_role_ids & set(exceed_role_ids):
        return MAX_RANK_IDX
    return cap_idx


# ============================================================
# Progress bar & display helpers
# ============================================================

def _progress_bar(xp: int, total: int = XP_PER_RANK, width: int = 10) -> str:
    filled = min(width, int(xp / total * width))
    return "█" * filled + "░" * (width - filled)


def _overall_rank_idx(attrs: dict) -> int:
    return min(attrs[k].get("rank_idx", 0) for k in _ATTR_KEYS)


# ============================================================
# Public embed function (exported for OrionProfileView Stats tab)
# ============================================================

def stats_embed(uid: str, char_name: str) -> discord.Embed:
    """Build the stats embed for the given player."""
    data = load_orion_players()
    player = data.get(uid, {})
    _ensure_attrs(player)
    attrs = player["attrs"]

    overall_idx = _overall_rank_idx(attrs)
    overall_rank = RANKS[overall_idx]

    embed = discord.Embed(
        title=f"⚔️ Player Stats — {char_name}",
        description=f"**Overall Rank: {overall_rank}**",
        color=0xe74c3c,
    )

    for a in ATTRS:
        key   = a["key"]
        emoji = a["emoji"]
        label = a["label"]
        entry = attrs.get(key, dict(_DEFAULT_ATTR_ENTRY))
        xp       = entry.get("xp", 0)
        rank_idx = entry.get("rank_idx", 0)
        rank_str = RANKS[rank_idx]
        bar      = _progress_bar(xp, XP_PER_RANK)
        embed.add_field(
            name=f"{emoji} {label}",
            value=f"`[{bar}]` {xp}/{XP_PER_RANK} XP    Rank: **{rank_str}**",
            inline=False,
        )

    embed.set_footer(text="Orion · Stats System")
    return embed


# ============================================================
# Training Minigames
# ============================================================

async def _mg_reaction_test(ix: discord.Interaction) -> bool:
    """⚡ ทดสอบปฏิกิริยา — ปุ่มปรากฏหลัง 1-3 วินาที ต้องกดภายใน 3 วินาที"""

    wait_sec = random.uniform(1.0, 3.0)

    # --- placeholder embed while waiting ---
    embed_wait = discord.Embed(
        title="⚡ ทดสอบปฏิกิริยา",
        description="🕐 เตรียมตัว... กดปุ่มให้เร็วที่สุดเมื่อมันปรากฏ!",
        color=0xf39c12,
    )

    # Disabled placeholder button
    placeholder_view = discord.ui.View(timeout=10)
    placeholder_btn = discord.ui.Button(
        label="รอสักครู่...",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        custom_id="mg_reaction_placeholder",
    )
    placeholder_view.add_item(placeholder_btn)

    await ix.followup.send(embed=embed_wait, view=placeholder_view, ephemeral=True)

    await asyncio.sleep(wait_sec)

    # --- now show the active button ---
    clicked = False
    result_event = asyncio.Event()

    active_view = discord.ui.View(timeout=3.0)

    async def _btn_callback(btn_ix: discord.Interaction):
        nonlocal clicked
        if str(btn_ix.user.id) != str(ix.user.id):
            await btn_ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True)
            return
        clicked = True
        result_event.set()
        await btn_ix.response.defer()

    active_btn = discord.ui.Button(
        label="⚡ กดเลย!",
        style=discord.ButtonStyle.success,
        custom_id="mg_reaction_active",
    )
    active_btn.callback = _btn_callback
    active_view.add_item(active_btn)

    embed_active = discord.Embed(
        title="⚡ ทดสอบปฏิกิริยา",
        description="**กดปุ่มด้านล่างให้เร็วที่สุด!**",
        color=0x2ecc71,
    )

    try:
        await ix.edit_original_response(embed=embed_active, view=active_view)
    except Exception:
        pass

    try:
        await asyncio.wait_for(result_event.wait(), timeout=3.0)
    except asyncio.TimeoutError:
        pass

    return clicked


async def _mg_sequence_memory(ix: discord.Interaction) -> bool:
    """🧠 จำลำดับ — แสดง 4 emoji 3 วินาที แล้วถามว่าอันไหนมาก่อน"""

    EMOJI_POOL = ["🔴", "🟡", "🟢", "🔵", "🟣", "🟠", "⚪", "⚫"]
    seq = random.sample(EMOJI_POOL, 4)
    first_emoji = seq[0]

    # show sequence
    embed_show = discord.Embed(
        title="🧠 จำลำดับ",
        description=(
            f"จำลำดับนี้ให้ได้!\n\n"
            f"**{' → '.join(seq)}**\n\n"
            "_คุณมี 3 วินาที..._"
        ),
        color=0x9b59b6,
    )

    dummy_view = discord.ui.View(timeout=5)
    await ix.followup.send(embed=embed_show, view=dummy_view, ephemeral=True)
    await asyncio.sleep(3.0)

    # shuffle buttons
    shuffled = list(seq)
    random.shuffle(shuffled)

    selected = None
    result_event = asyncio.Event()

    pick_view = discord.ui.View(timeout=20.0)

    def _make_callback(emoji_val: str):
        async def _cb(btn_ix: discord.Interaction):
            nonlocal selected
            if str(btn_ix.user.id) != str(ix.user.id):
                await btn_ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True)
                return
            selected = emoji_val
            result_event.set()
            await btn_ix.response.defer()
        return _cb

    for emoji_val in shuffled:
        b = discord.ui.Button(
            label=emoji_val,
            style=discord.ButtonStyle.primary,
        )
        b.callback = _make_callback(emoji_val)
        pick_view.add_item(b)

    embed_pick = discord.Embed(
        title="🧠 จำลำดับ",
        description="**emoji ตัวแรกในลำดับคือตัวไหน?**",
        color=0x9b59b6,
    )

    try:
        await ix.edit_original_response(embed=embed_pick, view=pick_view)
    except Exception:
        pass

    try:
        await asyncio.wait_for(result_event.wait(), timeout=20.0)
    except asyncio.TimeoutError:
        return False

    return selected == first_emoji


async def _mg_avoid_the_bomb(ix: discord.Interaction) -> bool:
    """💣 หลีกเลี่ยงระเบิด — 4 ปุ่ม A/B/C/D อันหนึ่งคือระเบิด"""

    labels = ["A", "B", "C", "D"]
    bomb_label = random.choice(labels)

    selected_label = None
    result_event = asyncio.Event()

    pick_view = discord.ui.View(timeout=20.0)

    def _make_callback(lbl: str):
        async def _cb(btn_ix: discord.Interaction):
            nonlocal selected_label
            if str(btn_ix.user.id) != str(ix.user.id):
                await btn_ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True)
                return
            selected_label = lbl
            result_event.set()
            await btn_ix.response.defer()
        return _cb

    for lbl in labels:
        b = discord.ui.Button(
            label=lbl,
            style=discord.ButtonStyle.primary,
        )
        b.callback = _make_callback(lbl)
        pick_view.add_item(b)

    embed = discord.Embed(
        title="💣 หลีกเลี่ยงระเบิด",
        description=(
            "หนึ่งในปุ่มด้านล่างคือ **💣 ระเบิด** — เลือกให้ถูก!\n\n"
            "_เลือก A, B, C หรือ D — หลีกเลี่ยงระเบิดให้ได้_"
        ),
        color=0xe74c3c,
    )

    await ix.followup.send(embed=embed, view=pick_view, ephemeral=True)

    try:
        await asyncio.wait_for(result_event.wait(), timeout=20.0)
    except asyncio.TimeoutError:
        return False

    return selected_label != bomb_label


async def _mg_type_word(ix: discord.Interaction) -> bool:
    """⌨️ พิมพ์คำ — แสดงคำ 5 ตัวอักษร ผู้เล่นพิมพ์ใน modal"""

    word = random.choice(_WORDS_5)

    embed = discord.Embed(
        title="⌨️ พิมพ์คำ",
        description=(
            f"พิมพ์คำด้านล่างนี้ให้ถูกต้องใน modal:\n\n"
            f"# `{word}`\n\n"
            "_กดปุ่ม **ป้อนคำ** แล้วพิมพ์ให้ตรง_"
        ),
        color=0x3498db,
    )

    submitted_word = None
    result_event = asyncio.Event()

    class TypeWordModal(discord.ui.Modal, title="⌨️ พิมพ์คำที่เห็น"):
        f_word = discord.ui.TextInput(
            label="พิมพ์คำที่เห็น (5 ตัวอักษร)",
            max_length=10,
            placeholder=word,
        )

        async def on_submit(self_modal, modal_ix: discord.Interaction):
            nonlocal submitted_word
            submitted_word = self_modal.f_word.value.strip().upper()
            result_event.set()
            await modal_ix.response.defer()

    class TypeWordView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30.0)

        @discord.ui.button(label="ป้อนคำ", style=discord.ButtonStyle.success)
        async def btn_type(self_view, btn_ix: discord.Interaction, _b):
            if str(btn_ix.user.id) != str(ix.user.id):
                await btn_ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True)
                return
            await btn_ix.response.send_modal(TypeWordModal())

    view = TypeWordView()
    await ix.followup.send(embed=embed, view=view, ephemeral=True)

    try:
        await asyncio.wait_for(result_event.wait(), timeout=30.0)
    except asyncio.TimeoutError:
        return False

    return submitted_word == word


_MINIGAMES = [
    _mg_reaction_test,
    _mg_sequence_memory,
    _mg_avoid_the_bomb,
    _mg_type_word,
]


# ============================================================
# XP & rank-up logic
# ============================================================

def _apply_xp(uid: str, attr_key: str, xp_gain: int) -> dict:
    """Add XP to attribute, handle rank-up. Returns updated entry dict."""
    data = load_orion_players()
    player = data[uid]
    _ensure_attrs(player)
    entry = player["attrs"][attr_key]
    cap_idx = _cap_for_player(uid)

    entry["xp"] += xp_gain
    ranked_up = False
    while entry["xp"] >= XP_PER_RANK and entry["rank_idx"] < cap_idx:
        entry["xp"] -= XP_PER_RANK
        entry["rank_idx"] += 1
        ranked_up = True

    # clamp xp if at cap
    if entry["rank_idx"] >= cap_idx:
        entry["xp"] = min(entry["xp"], XP_PER_RANK - 1)

    save_orion_players(data)
    return {"entry": dict(entry), "ranked_up": ranked_up}


# ============================================================
# Training flow views
# ============================================================

class TrainingAttrView(discord.ui.View):
    """Show 4 buttons, one per attribute. Player picks which to train."""

    def __init__(self, uid: str):
        super().__init__(timeout=120)
        self.uid = uid
        for i, a in enumerate(ATTRS):
            btn = discord.ui.Button(
                label=a["label"],
                emoji=a["emoji"],
                style=discord.ButtonStyle.primary,
                row=i,
                custom_id=f"train_attr_{a['key']}",
            )
            btn.callback = self._make_callback(a["key"], a["label"], a["emoji"])
            self.add_item(btn)

    def _make_callback(self, attr_key: str, attr_label: str, attr_emoji: str):
        async def _cb(btn_ix: discord.Interaction):
            if str(btn_ix.user.id) != self.uid:
                await btn_ix.response.send_message("ไม่ใช่เมนูของคุณ", ephemeral=True)
                return

            cfg = load_stats_config()
            cost = int(cfg.get("training_cost", 50))
            cooldown_sec = int(cfg.get("cooldown_seconds", 3600))

            # check cooldown
            data = load_orion_players()
            player = data.get(self.uid, {})
            _ensure_attrs(player)
            last_train = float(player.get("training_cooldown", 0))
            now = time.time()
            remaining = int(last_train + cooldown_sec - now)
            if remaining > 0:
                h, rem = divmod(remaining, 3600)
                m, s   = divmod(rem, 60)
                time_str = (f"{h}ชม. {m}นาที" if h else f"{m}นาที {s}วิ") if remaining >= 60 else f"{remaining}วิ"
                await btn_ix.response.send_message(
                    f"⏳ ยังไม่ถึงเวลาฝึก — รออีก **{time_str}**",
                    ephemeral=True,
                )
                return

            # check balance
            wallet = int(player.get("wallet", 0))
            if wallet < cost:
                await btn_ix.response.send_message(
                    f"❌ เงินไม่พอ — ต้องการ {money_str(cost)} (มี {money_str(wallet)})",
                    ephemeral=True,
                )
                return

            # deduct cost
            add_money(self.uid, -cost)

            # disable all buttons
            for child in self.children:
                child.disabled = True
            try:
                await btn_ix.response.edit_message(view=self)
            except Exception:
                await btn_ix.response.defer()

            # run random minigame
            mg_fn = random.choice(_MINIGAMES)
            success = await mg_fn(btn_ix)

            # apply XP
            if success:
                xp_gain = random.randint(cfg.get("exp_gain_min", 20), cfg.get("exp_gain_max", 50))
                result_color = 0x2ecc71
                result_title = "✅ ฝึกสำเร็จ!"
            else:
                half_min = max(1, cfg.get("exp_gain_min", 20) // 4)
                half_max = max(2, cfg.get("exp_gain_min", 20) // 2)
                xp_gain = random.randint(half_min, half_max)
                result_color = 0xe74c3c
                result_title = "❌ ล้มเหลว — ได้ XP เล็กน้อย"

            # apply boost multiplier if active
            boost_entry = cfg.get("exp_boosts", {}).get(self.uid)
            if boost_entry:
                exp_at = boost_entry.get("expires_at", 0)
                if exp_at == 0 or exp_at > now:
                    multiplier = float(boost_entry.get("multiplier", 1.0))
                    xp_gain = int(xp_gain * multiplier)

            apply_result = _apply_xp(self.uid, attr_key, xp_gain)
            entry = apply_result["entry"]
            ranked_up = apply_result["ranked_up"]

            # set cooldown
            data2 = load_orion_players()
            _ensure_attrs(data2[self.uid])
            data2[self.uid]["training_cooldown"] = now
            save_orion_players(data2)

            rank_str = RANKS[entry["rank_idx"]]
            xp       = entry["xp"]
            bar      = _progress_bar(xp, XP_PER_RANK)

            rank_up_line = f"\n🎉 **RANK UP! → {rank_str}**" if ranked_up else ""

            result_embed = discord.Embed(
                title=result_title,
                description=(
                    f"{attr_emoji} **{attr_label}**\n"
                    f"`[{bar}]` {xp}/{XP_PER_RANK} XP    Rank: **{rank_str}**\n"
                    f"+ {xp_gain} XP{rank_up_line}"
                ),
                color=result_color,
            )
            result_embed.set_footer(text=f"หักค่าฝึก {cost} | Orion · Stats")

            try:
                await btn_ix.followup.send(embed=result_embed, ephemeral=True)
            except Exception:
                pass

        return _cb


# ============================================================
# Admin Panel
# ============================================================

class StatsConfigModal(discord.ui.Modal, title="⚙️ ตั้งค่าระบบฝึกสถิติ"):
    f_cost     = discord.ui.TextInput(label="ค่าฝึก (training_cost)",     placeholder="50",   max_length=10)
    f_cooldown = discord.ui.TextInput(label="Cooldown (วินาที)",           placeholder="3600", max_length=10)
    f_cap      = discord.ui.TextInput(label="Rank Cap (เช่น B+, A, S-)",   placeholder="B+",   max_length=5)

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_stats_config()

        try:
            cost = int(self.f_cost.value.strip())
            cfg["training_cost"] = max(0, cost)
        except ValueError:
            await ix.response.send_message("❌ ค่าฝึกต้องเป็นตัวเลข", ephemeral=True)
            return

        try:
            cd = int(self.f_cooldown.value.strip())
            cfg["cooldown_seconds"] = max(0, cd)
        except ValueError:
            await ix.response.send_message("❌ cooldown ต้องเป็นตัวเลข", ephemeral=True)
            return

        cap_raw = self.f_cap.value.strip()
        if cap_raw not in RANKS:
            await ix.response.send_message(
                f"❌ Rank Cap ไม่ถูกต้อง — ต้องเป็นหนึ่งใน: {', '.join(RANKS)}",
                ephemeral=True,
            )
            return
        cfg["rank_cap"] = cap_raw

        save_stats_config(cfg)
        await ix.response.send_message(
            f"✅ บันทึกแล้ว — ค่าฝึก: **{cfg['training_cost']}** | "
            f"Cooldown: **{cfg['cooldown_seconds']}s** | "
            f"Rank Cap: **{cfg['rank_cap']}**",
            ephemeral=True,
        )


class ExceedCapRoleSelect(discord.ui.RoleSelect):
    def __init__(self, current_ids: list):
        super().__init__(
            placeholder="👑 เลือก Role ที่ข้ามแคป (เลือกได้หลาย role)",
            min_values=0,
            max_values=25,
        )

    async def callback(self, ix: discord.Interaction):
        cfg = load_stats_config()
        cfg["exceed_cap_role_ids"] = [str(r.id) for r in self.values]
        save_stats_config(cfg)
        if self.values:
            names = ", ".join(r.name for r in self.values)
            await ix.response.send_message(
                f"✅ ตั้ง Role ที่ข้ามแคปแล้ว: **{names}**",
                ephemeral=True,
            )
        else:
            await ix.response.send_message(
                "✅ ล้าง Role ที่ข้ามแคปแล้ว — ทุกคนใช้ rank cap ปกติ",
                ephemeral=True,
            )


class ExceedCapRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        cfg = load_stats_config()
        current_ids = cfg.get("exceed_cap_role_ids", [])
        self.add_item(ExceedCapRoleSelect(current_ids))


class ResetPlayerAttrUserSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="🔄 เลือกผู้เล่นที่จะรีเซ็ต attrs",
            min_values=1,
            max_values=1,
        )

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ ไม่ใช่ผู้เล่น", ephemeral=True)
            return
        uid = str(target.id)

        # reset attrs
        ensure_orion_player(uid)
        data = load_orion_players()
        _ensure_attrs(data[uid])
        for key in _ATTR_KEYS:
            data[uid]["attrs"][key] = dict(_DEFAULT_ATTR_ENTRY)
        data[uid]["training_cooldown"] = 0.0
        save_orion_players(data)

        await ix.response.send_message(
            f"✅ รีเซ็ต stats ของ **{target.display_name}** เป็น E- ทุก attribute แล้ว",
            ephemeral=True,
        )


class ResetPlayerAttrView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ResetPlayerAttrUserSelect())


# ── Admin: Edit Player Stats ───────────────────────────────────────────────────

class _AdminStatsEditPlayerSelect(discord.ui.UserSelect):
    def __init__(self):
        super().__init__(
            placeholder="✏️ เลือกผู้เล่นที่จะแก้ไข stats",
            min_values=1,
            max_values=1,
        )

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ ไม่ใช่ผู้เล่น", ephemeral=True)
            return
        uid = str(target.id)
        ensure_orion_player(uid)
        data = load_orion_players()
        _ensure_attrs(data[uid])
        player = data[uid]
        attrs = player.get("attrs", {})

        modal = _AdminStatsEditModal(uid, target.display_name, attrs, player)
        await ix.response.send_modal(modal)


class _AdminStatsEditModal(discord.ui.Modal, title="✏️ แก้ไข Stats ผู้เล่น"):
    # strength rank/xp
    f_str_rank = discord.ui.TextInput(label="Strength rank_idx (0-18)", max_length=3)
    f_str_xp   = discord.ui.TextInput(label="Strength XP (0-99)", max_length=3)
    # endurance
    f_end_rank = discord.ui.TextInput(label="Endurance rank_idx (0-18)", max_length=3)
    f_end_xp   = discord.ui.TextInput(label="Endurance XP (0-99)", max_length=3)

    def __init__(self, uid: str, display_name: str, attrs: dict, player: dict):
        super().__init__()
        self.uid = uid
        self.display_name = display_name
        self.title = f"✏️ แก้ไข Stats — {display_name[:30]}"
        # pre-fill
        self.f_str_rank.default = str(attrs.get("strength", {}).get("rank_idx", 0))
        self.f_str_xp.default   = str(attrs.get("strength", {}).get("xp", 0))
        self.f_end_rank.default = str(attrs.get("endurance", {}).get("rank_idx", 0))
        self.f_end_xp.default   = str(attrs.get("endurance", {}).get("xp", 0))

    async def on_submit(self, ix: discord.Interaction):
        data = load_orion_players()
        player = data.get(self.uid, {})
        _ensure_attrs(player)
        try:
            player["attrs"]["strength"]["rank_idx"]  = max(0, min(MAX_RANK_IDX, int(self.f_str_rank.value.strip())))
            player["attrs"]["strength"]["xp"]        = max(0, min(XP_PER_RANK - 1, int(self.f_str_xp.value.strip())))
            player["attrs"]["endurance"]["rank_idx"] = max(0, min(MAX_RANK_IDX, int(self.f_end_rank.value.strip())))
            player["attrs"]["endurance"]["xp"]       = max(0, min(XP_PER_RANK - 1, int(self.f_end_xp.value.strip())))
        except ValueError:
            await ix.response.send_message("❌ ค่าต้องเป็นตัวเลข", ephemeral=True)
            return
        data[self.uid] = player
        save_orion_players(data)
        await ix.response.send_message(
            f"✅ แก้ไข stats ของ **{self.display_name}** แล้ว "
            f"(Str: {RANKS[player['attrs']['strength']['rank_idx']]}, "
            f"End: {RANKS[player['attrs']['endurance']['rank_idx']]})",
            ephemeral=True,
        )


class _AdminStatsEditSpeedPercSelect(discord.ui.UserSelect):
    """Second modal — Speed, Perception, wallet."""
    def __init__(self):
        super().__init__(
            placeholder="✏️ แก้ไข Speed/Perception/Wallet",
            min_values=1,
            max_values=1,
        )

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ ไม่ใช่ผู้เล่น", ephemeral=True)
            return
        uid = str(target.id)
        ensure_orion_player(uid)
        data = load_orion_players()
        _ensure_attrs(data[uid])
        player = data[uid]
        attrs = player.get("attrs", {})
        modal = _AdminStatsEditModal2(uid, target.display_name, attrs, player)
        await ix.response.send_modal(modal)


class _AdminStatsEditModal2(discord.ui.Modal, title="✏️ แก้ไข Speed/Perception/Wallet"):
    f_spd_rank  = discord.ui.TextInput(label="Speed rank_idx (0-18)",      max_length=3)
    f_spd_xp    = discord.ui.TextInput(label="Speed XP (0-99)",            max_length=3)
    f_perc_rank = discord.ui.TextInput(label="Perception rank_idx (0-18)", max_length=3)
    f_perc_xp   = discord.ui.TextInput(label="Perception XP (0-99)",       max_length=3)

    def __init__(self, uid: str, display_name: str, attrs: dict, player: dict):
        super().__init__()
        self.uid = uid
        self.display_name = display_name
        self.f_spd_rank.default  = str(attrs.get("speed", {}).get("rank_idx", 0))
        self.f_spd_xp.default    = str(attrs.get("speed", {}).get("xp", 0))
        self.f_perc_rank.default = str(attrs.get("perception", {}).get("rank_idx", 0))
        self.f_perc_xp.default   = str(attrs.get("perception", {}).get("xp", 0))

    async def on_submit(self, ix: discord.Interaction):
        data = load_orion_players()
        player = data.get(self.uid, {})
        _ensure_attrs(player)
        try:
            player["attrs"]["speed"]["rank_idx"]       = max(0, min(MAX_RANK_IDX, int(self.f_spd_rank.value.strip())))
            player["attrs"]["speed"]["xp"]             = max(0, min(XP_PER_RANK - 1, int(self.f_spd_xp.value.strip())))
            player["attrs"]["perception"]["rank_idx"]  = max(0, min(MAX_RANK_IDX, int(self.f_perc_rank.value.strip())))
            player["attrs"]["perception"]["xp"]        = max(0, min(XP_PER_RANK - 1, int(self.f_perc_xp.value.strip())))
        except ValueError:
            await ix.response.send_message("❌ ค่าต้องเป็นตัวเลข", ephemeral=True)
            return
        data[self.uid] = player
        save_orion_players(data)
        await ix.response.send_message(
            f"✅ แก้ไข Speed/Perception ของ **{self.display_name}** แล้ว",
            ephemeral=True,
        )


class AdminStatsEditView(discord.ui.View):
    """View with two UserSelects for editing Str/End and Spd/Perc."""
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(_AdminStatsEditPlayerSelect())
        self.add_item(_AdminStatsEditSpeedPercSelect())


# ── Admin: Boost EXP ──────────────────────────────────────────────────────────

class _BoostAddModal(discord.ui.Modal, title="🚀 เพิ่ม EXP Boost"):
    f_uid        = discord.ui.TextInput(label="User ID", max_length=25)
    f_multiplier = discord.ui.TextInput(label="Multiplier (เช่น 1.5, 2.0)", max_length=10)
    f_hours      = discord.ui.TextInput(
        label="ระยะเวลา (ชั่วโมง, 0 = ถาวร)", max_length=10, placeholder="0",
    )

    async def on_submit(self, ix: discord.Interaction):
        try:
            uid_val  = self.f_uid.value.strip()
            mult     = float(self.f_multiplier.value.strip())
            hours    = float(self.f_hours.value.strip() or "0")
        except ValueError:
            await ix.response.send_message("❌ ค่าไม่ถูกต้อง", ephemeral=True)
            return
        expires_at = 0.0 if hours <= 0 else time.time() + hours * 3600
        cfg = load_stats_config()
        cfg.setdefault("exp_boosts", {})[uid_val] = {
            "multiplier": mult,
            "expires_at": expires_at,
        }
        save_stats_config(cfg)
        dur_str = "ถาวร" if expires_at == 0 else f"{hours:.1f} ชม."
        await ix.response.send_message(
            f"✅ เพิ่ม Boost ×**{mult}** ให้ <@{uid_val}> ({dur_str})",
            ephemeral=True,
        )


class _BoostRemoveModal(discord.ui.Modal, title="🗑️ ลบ EXP Boost"):
    f_uid = discord.ui.TextInput(label="User ID ที่จะลบ Boost", max_length=25)

    async def on_submit(self, ix: discord.Interaction):
        uid_val = self.f_uid.value.strip()
        cfg = load_stats_config()
        boosts = cfg.get("exp_boosts", {})
        if uid_val in boosts:
            del boosts[uid_val]
            cfg["exp_boosts"] = boosts
            save_stats_config(cfg)
            await ix.response.send_message(f"✅ ลบ Boost ของ <@{uid_val}> แล้ว", ephemeral=True)
        else:
            await ix.response.send_message(f"❌ ไม่พบ Boost สำหรับ `{uid_val}`", ephemeral=True)


class _BoostEXPView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="📋 ดู Boosts ทั้งหมด", style=discord.ButtonStyle.primary, row=0)
    async def btn_list(self, ix: discord.Interaction, _b):
        cfg    = load_stats_config()
        boosts = cfg.get("exp_boosts", {})
        now    = time.time()
        if not boosts:
            await ix.response.send_message("ยังไม่มี Boost ที่ใช้งานอยู่", ephemeral=True)
            return
        lines = []
        for uid_val, entry in boosts.items():
            mult   = entry.get("multiplier", 1.0)
            exp_at = entry.get("expires_at", 0)
            if exp_at == 0:
                dur = "ถาวร"
            elif exp_at > now:
                hrs = int((exp_at - now) / 3600)
                dur = f"{hrs}ชม. เหลือ"
            else:
                dur = "หมดอายุ"
            lines.append(f"• <@{uid_val}> — ×{mult} ({dur})")
        await ix.response.send_message(
            "**🚀 EXP Boosts ทั้งหมด:**\n" + "\n".join(lines),
            ephemeral=True,
        )

    @discord.ui.button(label="➕ เพิ่ม Boost", style=discord.ButtonStyle.success, row=0)
    async def btn_add(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_BoostAddModal())

    @discord.ui.button(label="🗑️ ลบ Boost", style=discord.ButtonStyle.danger, row=0)
    async def btn_remove(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_BoostRemoveModal())


class StatsAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚙️ ตั้งค่า", style=discord.ButtonStyle.primary, row=0)
    async def btn_config(self, ix: discord.Interaction, _b):
        cfg = load_stats_config()
        modal = StatsConfigModal()
        modal.f_cost.default     = str(cfg.get("training_cost", 50))
        modal.f_cooldown.default = str(cfg.get("cooldown_seconds", 3600))
        modal.f_cap.default      = cfg.get("rank_cap", DEFAULT_CAP)
        await ix.response.send_modal(modal)

    @discord.ui.button(label="👑 Role ที่ข้ามแคป", style=discord.ButtonStyle.secondary, row=0)
    async def btn_exceed_role(self, ix: discord.Interaction, _b):
        await ix.response.send_message(
            "👑 เลือก Role ที่สามารถข้ามแคป rank ปกติ (จะได้ EX ได้):",
            view=ExceedCapRoleView(),
            ephemeral=True,
        )

    @discord.ui.button(label="🔄 รีเซ็ตผู้เล่น", style=discord.ButtonStyle.danger, row=0)
    async def btn_reset_player(self, ix: discord.Interaction, _b):
        await ix.response.send_message(
            "🔄 เลือกผู้เล่นที่จะรีเซ็ต attrs กลับ E-:",
            view=ResetPlayerAttrView(),
            ephemeral=True,
        )

    @discord.ui.button(label="✏️ แก้ไข Stats ผู้เล่น", style=discord.ButtonStyle.secondary, row=1)
    async def btn_edit_stats(self, ix: discord.Interaction, _b):
        await ix.response.send_message(
            "✏️ เลือกผู้เล่นที่จะแก้ไข Stats (แถวบน = Str/End, แถวล่าง = Spd/Perc):",
            view=AdminStatsEditView(),
            ephemeral=True,
        )

    @discord.ui.button(label="🚀 จัดการ EXP Boost", style=discord.ButtonStyle.secondary, row=1)
    async def btn_boost_exp(self, ix: discord.Interaction, _b):
        await ix.response.send_message(
            "🚀 จัดการ EXP Boost สำหรับผู้เล่น:",
            view=_BoostEXPView(),
            ephemeral=True,
        )

    @discord.ui.button(label="❌ ปิด", style=discord.ButtonStyle.secondary, row=2)
    async def btn_close(self, ix: discord.Interaction, _b):
        try:
            await ix.response.edit_message(content="✓ ปิดแล้ว", embed=None, view=None)
        except Exception:
            await ix.response.defer()


# ============================================================
# Slash Commands
# ============================================================

def _stats_admin_embed() -> discord.Embed:
    cfg = load_stats_config()
    cap      = cfg.get("rank_cap", DEFAULT_CAP)
    cost     = cfg.get("training_cost", 50)
    cooldown = cfg.get("cooldown_seconds", 3600)
    exceed   = cfg.get("exceed_cap_role_ids", [])
    exceed_str = ", ".join(f"<@&{r}>" for r in exceed) if exceed else "_ไม่มี_"
    h, rem = divmod(int(cooldown), 3600)
    m = rem // 60
    cd_str = (f"{h}ชม. {m}นาที" if h else f"{m}นาที") if cooldown >= 60 else f"{cooldown}วิ"

    embed = discord.Embed(
        title="⚔️  Stats System — Admin Panel",
        description=(
            f"**Rank Cap:** `{cap}`\n"
            f"**ค่าฝึก:** `{cost:,}`\n"
            f"**Cooldown:** `{cd_str}`\n"
            f"**Roles ข้ามแคป:** {exceed_str}\n\n"
            "**Ranks:** " + " → ".join(RANKS)
        ),
        color=0xe74c3c,
    )
    embed.set_footer(text="Orion · Stats Admin")
    return embed


@bot.tree.command(name="ฝึกสถิติ", description="ฝึก attribute ของตัวละคร (Strength / Endurance / Speed / Perception)", guild=_ORION_GUILD_OBJ)
async def cmd_train_stats(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True)
        return

    uid = str(interaction.user.id)
    ensure_player_attrs(uid)

    data   = load_orion_players()
    player = data.get(uid, {})
    _ensure_attrs(player)
    cfg    = load_stats_config()
    cost   = int(cfg.get("training_cost", 50))
    cooldown_sec = int(cfg.get("cooldown_seconds", 3600))

    # cooldown check
    last_train = float(player.get("training_cooldown", 0))
    now        = time.time()
    remaining  = int(last_train + cooldown_sec - now)

    char_name = player.get("char_name") or interaction.user.display_name
    embed = stats_embed(uid, char_name)

    if remaining > 0:
        h, rem = divmod(remaining, 3600)
        m, s   = divmod(rem, 60)
        time_str = (f"{h}ชม. {m}นาที" if h else f"{m}นาที {s}วิ") if remaining >= 60 else f"{remaining}วิ"
        embed.description = (
            f"{embed.description}\n\n"
            f"⏳ **คูลดาวน์ยังไม่หมด** — รออีก **{time_str}**\n"
            "_ดูสถิติปัจจุบันของคุณด้านบน_"
        )
        embed.color = discord.Color.orange()
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # balance check
    wallet = int(player.get("wallet", 0))
    if wallet < cost:
        await interaction.response.send_message(
            f"❌ เงินไม่พอ — ต้องการ {money_str(cost)} (มี {money_str(wallet)})",
            ephemeral=True,
        )
        return

    embed.description = (
        f"{embed.description}\n\n"
        f"ค่าฝึก: {money_str(cost)}\n"
        "_เลือก attribute ที่จะฝึก:_"
    )

    await interaction.response.send_message(
        embed=embed,
        view=TrainingAttrView(uid),
        ephemeral=True,
    )


@bot.tree.command(name="ฝึกสถิติแอดมิน", description="[Admin] จัดการระบบ Stats / Training", guild=_ORION_GUILD_OBJ)
async def cmd_train_stats_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True)
        return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True)
        return

    await interaction.response.send_message(
        embed=_stats_admin_embed(),
        view=StatsAdminView(),
        ephemeral=True,
    )
