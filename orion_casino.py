# ============================================================
# ORION — Casino System
# ============================================================
# - 4 solo games: Coinflip / Dice / Roulette / Higher-Lower
# - 1 multi-player room game: Roulette (เปิดห้อง → คนอื่นโจอิน + วางเดิมพัน → เจ้าของกด Spin)
# - บอทประกาศผลในห้องสาธารณะเพื่อความโปร่งใส
# ============================================================

import sys
import time
import json
import uuid as _uuid
import random as _rand
import discord

_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_casino ต้องถูก import จาก orion_bot.py")

bot                  = _orion_bot_mod.bot
ORION_GUILD_ID       = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ     = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR       = _orion_bot_mod.ORION_DATA_DIR
load_json            = _orion_bot_mod.load_json
save_json            = _orion_bot_mod.save_json
ensure_orion_player  = _orion_bot_mod.ensure_orion_player
load_currency_cfg    = _orion_bot_mod.load_currency_cfg
money_str            = _orion_bot_mod.money_str
get_wallet           = _orion_bot_mod.get_wallet
add_money            = _orion_bot_mod.add_money
_parse_int           = _orion_bot_mod._parse_int
make_menu_embed      = _orion_bot_mod.make_menu_embed


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


CASINO_ROOMS_FILE  = f"{ORION_DATA_DIR}/casino_rooms.json"
CASINO_CONFIG_FILE = f"{ORION_DATA_DIR}/casino_config.json"

# ── Default config — admin ปรับได้ผ่าน /คาสิโนแอดมิน ──
DEFAULT_CASINO_CFG = {
    "global_min_bet":   1,
    "global_max_bet":   100000,
    "games": {
        "coinflip": {
            "enabled":   True,
            "payout_x":  1.95,      # win multiplier ของเดิมพัน
            "win_chance_bonus": 0,  # บวกเข้าโอกาสชนะของผู้เล่น (0=ปกติ 50%, -10 = แย่ลง 10%)
        },
        "dice": {
            "enabled":   True,
            "payout_x":  5,          # ปกติ x5 (1/6 ชนะ)
            "win_chance_bonus": 0,
        },
        "hilo": {
            "enabled":   True,
            "payout_x":  1.95,
            "win_chance_bonus": 0,
        },
        "roulette": {
            "enabled":          True,
            "number_payout_x":  35,
            "color_payout_x":   2,
            "evenodd_payout_x": 2,
            "win_chance_bonus": 0,
        },
    },
}


def load_casino_cfg() -> dict:
    cfg = load_json(CASINO_CONFIG_FILE, {})
    # backfill defaults
    changed = False
    for k, v in DEFAULT_CASINO_CFG.items():
        if k not in cfg:
            cfg[k] = v if not isinstance(v, dict) else dict(v); changed = True
    if "games" in cfg:
        for gk, gv in DEFAULT_CASINO_CFG["games"].items():
            if gk not in cfg["games"]:
                cfg["games"][gk] = dict(gv); changed = True
            else:
                for fk, fv in gv.items():
                    if fk not in cfg["games"][gk]:
                        cfg["games"][gk][fk] = fv; changed = True
    if changed:
        save_casino_cfg(cfg)
    return cfg


def save_casino_cfg(cfg: dict):
    save_json(CASINO_CONFIG_FILE, cfg)


def _bet_ok(bet: int) -> bool:
    cfg = load_casino_cfg()
    return cfg["global_min_bet"] <= bet <= cfg["global_max_bet"]


def _game_on(key: str) -> bool:
    cfg = load_casino_cfg()
    return cfg.get("games", {}).get(key, {}).get("enabled", True)


def load_rooms() -> dict:
    return load_json(CASINO_ROOMS_FILE, {})


def save_rooms(d: dict):
    save_json(CASINO_ROOMS_FILE, d)


def _new_id() -> str:
    return _uuid.uuid4().hex[:6]


# ════════════════════════════════════════════════════════════
# SOLO GAMES
# ════════════════════════════════════════════════════════════

# ── Coinflip ─────────────────────────────────────────────────
async def _solo_coinflip(ix: discord.Interaction, bet: int, choice: str):
    uid = str(ix.user.id)
    cfg = load_casino_cfg()
    g = cfg["games"]["coinflip"]
    if not g["enabled"]:
        await ix.response.send_message("❌ เกม Coinflip ถูกปิดอยู่", ephemeral=True); return
    if not _bet_ok(bet):
        await ix.response.send_message(f"❌ เดิมพันต้องอยู่ {cfg['global_min_bet']:,}-{cfg['global_max_bet']:,}", ephemeral=True); return
    if get_wallet(uid) < bet:
        await ix.response.send_message("❌ เงินไม่พอ", ephemeral=True); return
    # win_chance_bonus: ปรับโอกาสจาก 50% (เป็น %)
    win_chance = 50 + int(g.get("win_chance_bonus", 0))
    won_roll = _rand.randint(1, 100) <= win_chance
    result = choice if won_roll else ("tails" if choice == "heads" else "heads")
    won = (choice == result)
    if won:
        payout_x = float(g.get("payout_x", 1.95))
        winnings = int(bet * payout_x) - bet
        add_money(uid, winnings)
        net = winnings
        verdict = f"🎉 **ชนะ!** ออก **{result.upper()}** — ได้ {money_str(winnings)} (กำไรสุทธิ)"
        color = 0x2ecc71
    else:
        add_money(uid, -bet)
        net = -bet
        verdict = f"💔 **แพ้** ออก **{result.upper()}** — เสีย {money_str(bet)}"
        color = 0xe74c3c
    embed = discord.Embed(
        title="🪙 Coinflip",
        description=(
            f"**ผู้เล่น:** {ix.user.mention}\n"
            f"**เลือก:** {choice.upper()}  ·  **ออก:** {result.upper()}\n"
            f"**เดิมพัน:** {money_str(bet)}\n\n{verdict}\n"
            f"_ยอดสุทธิ_  {'+' if net >= 0 else ''}{net:,}  ·  _เงินคงเหลือ_  {get_wallet(uid):,}"
        ),
        color=color,
    )
    await ix.response.send_message(embed=embed, ephemeral=False)


class CoinflipBetModal(discord.ui.Modal, title="Coinflip — วางเดิมพัน"):
    f_bet = discord.ui.TextInput(label="จำนวนเดิมพัน", placeholder="100", max_length=10)

    def __init__(self, choice: str):
        super().__init__()
        self.choice = choice

    async def on_submit(self, ix):
        bet = max(1, _parse_int(self.f_bet.value, 0) or 0)
        await _solo_coinflip(ix, bet, self.choice)


class CoinflipPickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="Heads", style=discord.ButtonStyle.primary, row=1)
    async def b_h(self, ix, _b): await ix.response.send_modal(CoinflipBetModal("heads"))

    @discord.ui.button(label="Tails", style=discord.ButtonStyle.primary, row=2)
    async def b_t(self, ix, _b): await ix.response.send_modal(CoinflipBetModal("tails"))


# ── Dice ─────────────────────────────────────────────────────
async def _solo_dice(ix: discord.Interaction, bet: int, pick: int):
    uid = str(ix.user.id)
    cfg = load_casino_cfg()
    g = cfg["games"]["dice"]
    if not g["enabled"]:
        await ix.response.send_message("❌ เกม Dice ถูกปิดอยู่", ephemeral=True); return
    if not _bet_ok(bet):
        await ix.response.send_message(f"❌ เดิมพันต้องอยู่ {cfg['global_min_bet']:,}-{cfg['global_max_bet']:,}", ephemeral=True); return
    if get_wallet(uid) < bet:
        await ix.response.send_message("❌ เงินไม่พอ", ephemeral=True); return
    # base 16.67% win → +bonus
    win_chance = int(100/6) + int(g.get("win_chance_bonus", 0))
    if _rand.randint(1, 100) <= win_chance:
        roll = pick
    else:
        roll = _rand.choice([n for n in range(1, 7) if n != pick])
    won = (pick == roll)
    if won:
        payout_x = float(g.get("payout_x", 5))
        winnings = int(bet * payout_x) - bet
        add_money(uid, winnings)
        net = winnings
        verdict = f"🎉 **ชนะ!** ลูกเต๋าออก **{roll}** — ได้ {money_str(winnings)} (×{payout_x})"
        color = 0x2ecc71
    else:
        add_money(uid, -bet)
        net = -bet
        verdict = f"💔 **แพ้** ลูกเต๋าออก **{roll}** — เสีย {money_str(bet)}"
        color = 0xe74c3c
    embed = discord.Embed(
        title="🎲 Dice",
        description=(
            f"**ผู้เล่น:** {ix.user.mention}\n"
            f"**เลือก:** {pick}  ·  **ออก:** {roll}\n"
            f"**เดิมพัน:** {money_str(bet)}\n\n{verdict}\n"
            f"_ยอดสุทธิ_  {'+' if net >= 0 else ''}{net:,}  ·  _เงินคงเหลือ_  {get_wallet(uid):,}"
        ),
        color=color,
    )
    await ix.response.send_message(embed=embed, ephemeral=False)


class DiceBetModal(discord.ui.Modal, title="Dice — วางเดิมพัน"):
    f_pick = discord.ui.TextInput(label="ทายเลข (1-6)", placeholder="1", max_length=1)
    f_bet  = discord.ui.TextInput(label="จำนวนเดิมพัน", placeholder="100", max_length=10)

    async def on_submit(self, ix):
        pick = _parse_int(self.f_pick.value, 0) or 0
        if not 1 <= pick <= 6:
            await ix.response.send_message("❌ ต้องเป็น 1-6", ephemeral=True); return
        bet = max(1, _parse_int(self.f_bet.value, 0) or 0)
        await _solo_dice(ix, bet, pick)


# ── Higher / Lower ───────────────────────────────────────────
async def _solo_hilo(ix: discord.Interaction, bet: int, guess: str, first: int):
    uid = str(ix.user.id)
    cfg = load_casino_cfg()
    g = cfg["games"]["hilo"]
    if not g["enabled"]:
        await ix.response.send_message("❌ เกม Higher/Lower ถูกปิดอยู่", ephemeral=True); return
    if not _bet_ok(bet):
        await ix.response.send_message(f"❌ เดิมพันต้องอยู่ {cfg['global_min_bet']:,}-{cfg['global_max_bet']:,}", ephemeral=True); return
    if get_wallet(uid) < bet:
        await ix.response.send_message("❌ เงินไม่พอ", ephemeral=True); return
    # base ~50% → +bonus
    win_chance = 50 + int(g.get("win_chance_bonus", 0))
    won_roll = _rand.randint(1, 100) <= win_chance
    if won_roll:
        # ทำให้ correct โดย pick second ที่ตรงทาง
        if guess == "higher":
            pool = list(range(first+1, 14)) or list(range(1, first))
        else:
            pool = list(range(1, first)) or list(range(first+1, 14))
        second = _rand.choice(pool)
    else:
        if guess == "higher":
            pool = list(range(1, first)) or list(range(first+1, 14))
        else:
            pool = list(range(first+1, 14)) or list(range(1, first))
        second = _rand.choice(pool)
    correct = (guess == "higher" and second > first) or (guess == "lower" and second < first)
    if correct:
        payout_x = float(g.get("payout_x", 1.95))
        winnings = int(bet * payout_x) - bet
        add_money(uid, winnings)
        net = winnings
        verdict = f"🎉 **ชนะ!** การ์ดถัดไปคือ **{second}** — ได้ {money_str(winnings)}"
        color = 0x2ecc71
    else:
        add_money(uid, -bet)
        net = -bet
        verdict = f"💔 **แพ้** การ์ดถัดไปคือ **{second}** — เสีย {money_str(bet)}"
        color = 0xe74c3c
    embed = discord.Embed(
        title="📈 Higher / Lower",
        description=(
            f"**ผู้เล่น:** {ix.user.mention}\n"
            f"**การ์ดแรก:** {first}  ·  **ทาย:** {guess.upper()}  ·  **ถัดไป:** {second}\n"
            f"**เดิมพัน:** {money_str(bet)}\n\n{verdict}\n"
            f"_ยอดสุทธิ_  {'+' if net >= 0 else ''}{net:,}  ·  _เงินคงเหลือ_  {get_wallet(uid):,}"
        ),
        color=color,
    )
    await ix.response.send_message(embed=embed, ephemeral=False)


class HiLoStartView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.first = _rand.randint(1, 13)

    async def _prompt(self, ix, guess):
        await ix.response.send_modal(HiLoBetModal(guess, self.first))

    @discord.ui.button(label="Higher", style=discord.ButtonStyle.success, row=1)
    async def b_h(self, ix, _b): await self._prompt(ix, "higher")

    @discord.ui.button(label="Lower", style=discord.ButtonStyle.danger, row=2)
    async def b_l(self, ix, _b): await self._prompt(ix, "lower")


class HiLoBetModal(discord.ui.Modal, title="Higher/Lower — วางเดิมพัน"):
    f_bet = discord.ui.TextInput(label="จำนวนเดิมพัน", placeholder="100", max_length=10)

    def __init__(self, guess: str, first: int):
        super().__init__()
        self.guess = guess
        self.first = first

    async def on_submit(self, ix):
        bet = max(1, _parse_int(self.f_bet.value, 0) or 0)
        await _solo_hilo(ix, bet, self.guess, self.first)


# ── Roulette (solo) ──────────────────────────────────────────
async def _solo_roulette(ix: discord.Interaction, bet: int, choice_type: str, choice_val):
    uid = str(ix.user.id)
    cfg = load_casino_cfg()
    g = cfg["games"]["roulette"]
    if not g["enabled"]:
        await ix.response.send_message("❌ เกม Roulette ถูกปิดอยู่", ephemeral=True); return
    if not _bet_ok(bet):
        await ix.response.send_message(f"❌ เดิมพันต้องอยู่ {cfg['global_min_bet']:,}-{cfg['global_max_bet']:,}", ephemeral=True); return
    if get_wallet(uid) < bet:
        await ix.response.send_message("❌ เงินไม่พอ", ephemeral=True); return
    roll = _rand.randint(0, 36)
    # red: 1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36
    # black: 2,4,6,8,10,11,13,15,17,20,22,24,26,28,29,31,33,35
    # 0: green
    reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    color_of = "red" if roll in reds else ("black" if roll != 0 else "green")
    won = False
    payout_x = 0
    if choice_type == "number":
        won = (roll == choice_val)
        payout_x = float(g.get("number_payout_x", 35))
    elif choice_type == "color":
        won = (color_of == choice_val)
        payout_x = float(g.get("color_payout_x", 2))
    elif choice_type == "even_odd":
        if roll == 0:
            won = False
        else:
            won = (roll % 2 == 0 and choice_val == "even") or (roll % 2 == 1 and choice_val == "odd")
        payout_x = float(g.get("evenodd_payout_x", 2))
    if won:
        winnings = int(bet * payout_x) - bet
        add_money(uid, winnings)
        net = winnings
        verdict = f"🎉 **ชนะ!** ลูกบอลตก **{roll} {color_of.upper()}** — ได้ {money_str(winnings)}"
        color = 0x2ecc71
    else:
        add_money(uid, -bet)
        net = -bet
        verdict = f"💔 **แพ้** ลูกบอลตก **{roll} {color_of.upper()}** — เสีย {money_str(bet)}"
        color = 0xe74c3c
    embed = discord.Embed(
        title="🎰 Roulette",
        description=(
            f"**ผู้เล่น:** {ix.user.mention}\n"
            f"**ทาย:** {choice_type} = {choice_val}  ·  **ผล:** {roll} ({color_of})\n"
            f"**เดิมพัน:** {money_str(bet)}\n\n{verdict}\n"
            f"_ยอดสุทธิ_  {'+' if net >= 0 else ''}{net:,}  ·  _เงินคงเหลือ_  {get_wallet(uid):,}"
        ),
        color=color,
    )
    await ix.response.send_message(embed=embed, ephemeral=False)


class RoulettePickView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="ทายเลข (×35)", style=discord.ButtonStyle.primary, row=1)
    async def b_n(self, ix, _b): await ix.response.send_modal(RouletteNumberModal())

    @discord.ui.button(label="แดง (×2)", style=discord.ButtonStyle.danger, row=2)
    async def b_r(self, ix, _b): await ix.response.send_modal(RouletteColorBetModal("red"))

    @discord.ui.button(label="ดำ (×2)", style=discord.ButtonStyle.secondary, row=3)
    async def b_b(self, ix, _b): await ix.response.send_modal(RouletteColorBetModal("black"))

    @discord.ui.button(label="คู่ (×2)", style=discord.ButtonStyle.success, row=4)
    async def b_e(self, ix, _b): await ix.response.send_modal(RouletteEvenOddBetModal("even"))


class RouletteNumberModal(discord.ui.Modal, title="Roulette — ทายเลข"):
    f_n   = discord.ui.TextInput(label="ทายเลข (0-36)", placeholder="17", max_length=2)
    f_bet = discord.ui.TextInput(label="จำนวนเดิมพัน", placeholder="100", max_length=10)

    async def on_submit(self, ix):
        n = _parse_int(self.f_n.value, -1)
        if n is None or not 0 <= n <= 36:
            await ix.response.send_message("❌ ต้องเป็น 0-36", ephemeral=True); return
        bet = max(1, _parse_int(self.f_bet.value, 0) or 0)
        await _solo_roulette(ix, bet, "number", n)


class RouletteColorBetModal(discord.ui.Modal, title="Roulette — เดิมพันสี"):
    f_bet = discord.ui.TextInput(label="จำนวนเดิมพัน", placeholder="100", max_length=10)

    def __init__(self, color: str):
        super().__init__()
        self.color = color

    async def on_submit(self, ix):
        bet = max(1, _parse_int(self.f_bet.value, 0) or 0)
        await _solo_roulette(ix, bet, "color", self.color)


class RouletteEvenOddBetModal(discord.ui.Modal, title="Roulette — คู่/คี่"):
    f_bet = discord.ui.TextInput(label="จำนวนเดิมพัน", placeholder="100", max_length=10)

    def __init__(self, eo: str):
        super().__init__()
        self.eo = eo

    async def on_submit(self, ix):
        bet = max(1, _parse_int(self.f_bet.value, 0) or 0)
        await _solo_roulette(ix, bet, "even_odd", self.eo)


# ════════════════════════════════════════════════════════════
# MULTI-PLAYER ROOMS (Roulette — เป่ายังเปิดได้)
# ════════════════════════════════════════════════════════════

class RoomCreateModal(discord.ui.Modal, title="สร้างห้องคาสิโน (Roulette)"):
    f_min  = discord.ui.TextInput(label="เดิมพันขั้นต่ำ", placeholder="50", max_length=8)
    f_max  = discord.ui.TextInput(label="เดิมพันสูงสุด", placeholder="500", max_length=8)
    f_cap  = discord.ui.TextInput(label="ผู้เล่นสูงสุด", placeholder="6", max_length=2)

    async def on_submit(self, ix: discord.Interaction):
        rooms = load_rooms()
        rid = _new_id()
        rooms[rid] = {
            "owner_id":   str(ix.user.id),
            "game":       "roulette",
            "channel_id": ix.channel.id if ix.channel else 0,
            "status":     "open",
            "players":    [],
            "min_bet":    max(1, _parse_int(self.f_min.value, 50) or 50),
            "max_bet":    max(1, _parse_int(self.f_max.value, 500) or 500),
            "max_players": max(2, _parse_int(self.f_cap.value, 6) or 6),
            "created_at": int(time.time()),
        }
        save_rooms(rooms)
        await ix.response.send_message(
            content=f"🎰 **ห้องคาสิโนเปิดแล้ว!** ID: `{rid}` · ผู้เล่นสูงสุด {rooms[rid]['max_players']}\n"
                    f"ใช้ `/คาสิโนห้อง` แล้วกด Join เพื่อเข้าร่วม",
            embed=_room_embed(rid, rooms[rid]),
            ephemeral=False,
        )


def _room_embed(rid: str, room: dict) -> discord.Embed:
    status_text = {"open": "🟢 เปิดรับ", "playing": "🟡 กำลังเล่น", "closed": "🔴 ปิด"}.get(room["status"], "?")
    lines = []
    for p in room.get("players", []):
        choice = p.get("choice", "—")
        cval = p.get("choice_val", "—")
        lines.append(f"<@{p['uid']}> · เดิมพัน {p['bet']:,} · ทาย `{choice}={cval}`")
    embed = discord.Embed(
        title=f"Roulette Room · `{rid}`",
        description=(
            f"**Owner:** <@{room['owner_id']}>\n"
            f"**Status:** {status_text}\n"
            f"**Bet range:** {room['min_bet']:,} — {room['max_bet']:,}\n"
            f"**Players:** {len(room.get('players',[]))}/{room['max_players']}\n\n"
            + ("\n".join(lines) or "_(ยังไม่มีคนเข้า)_")
        ),
        color=0x9b59b6,
    )
    return embed


class RoomJoinView(discord.ui.View):
    def __init__(self, rid: str):
        super().__init__(timeout=600)
        self.rid = rid

    @discord.ui.button(label="Join + Bet", style=discord.ButtonStyle.success, row=1)
    async def b_join(self, ix, _b):
        rooms = load_rooms()
        room = rooms.get(self.rid)
        if not room or room["status"] != "open":
            await ix.response.send_message("❌ ห้องไม่เปิดอยู่", ephemeral=True); return
        if len(room["players"]) >= room["max_players"]:
            await ix.response.send_message("❌ ห้องเต็ม", ephemeral=True); return
        uid = str(ix.user.id)
        if any(p["uid"] == uid for p in room["players"]):
            await ix.response.send_message("⚠️ คุณอยู่ในห้องนี้แล้ว", ephemeral=True); return
        await ix.response.send_modal(RoomBetModal(self.rid))

    @discord.ui.button(label="Spin (Owner)", style=discord.ButtonStyle.primary, row=2)
    async def b_spin(self, ix, _b):
        rooms = load_rooms()
        room = rooms.get(self.rid)
        if not room:
            await ix.response.send_message("❌ ไม่พบห้อง", ephemeral=True); return
        if str(ix.user.id) != room["owner_id"]:
            await ix.response.send_message("❌ เจ้าของห้องเท่านั้น", ephemeral=True); return
        if not room["players"]:
            await ix.response.send_message("❌ ยังไม่มีคนวางเดิมพัน", ephemeral=True); return
        await _spin_roulette_room(ix, self.rid)

    @discord.ui.button(label="ปิดห้อง", style=discord.ButtonStyle.danger, row=3)
    async def b_close(self, ix, _b):
        rooms = load_rooms()
        room = rooms.get(self.rid)
        if not room:
            await ix.response.send_message("❌ ไม่พบห้อง", ephemeral=True); return
        if str(ix.user.id) != room["owner_id"]:
            await ix.response.send_message("❌ เจ้าของห้องเท่านั้น", ephemeral=True); return
        # คืนเดิมพันให้ผู้เล่นที่ยังไม่ได้เล่น
        for p in room["players"]:
            add_money(p["uid"], int(p["bet"]))
        room["status"] = "closed"
        save_rooms(rooms)
        await ix.response.send_message(f"✅ ปิดห้อง `{self.rid}` แล้ว — คืนเดิมพันให้ผู้เล่นทุกคน", ephemeral=False)


class RoomBetModal(discord.ui.Modal, title="วางเดิมพันในห้อง"):
    f_bet  = discord.ui.TextInput(label="จำนวนเดิมพัน", placeholder="100", max_length=10)
    f_type = discord.ui.TextInput(label="ทาย: number / red / black / even / odd", placeholder="red", max_length=10)
    f_val  = discord.ui.TextInput(label="ถ้าทาย number ใส่ 0-36 (อื่นๆเว้นว่าง)", required=False, max_length=2)

    def __init__(self, rid: str):
        super().__init__()
        self.rid = rid

    async def on_submit(self, ix: discord.Interaction):
        rooms = load_rooms()
        room = rooms.get(self.rid)
        if not room or room["status"] != "open":
            await ix.response.send_message("❌ ห้องไม่เปิด", ephemeral=True); return
        bet = max(1, _parse_int(self.f_bet.value, 0) or 0)
        if not (room["min_bet"] <= bet <= room["max_bet"]):
            await ix.response.send_message(f"❌ เดิมพันต้องอยู่ {room['min_bet']:,}-{room['max_bet']:,}", ephemeral=True); return
        uid = str(ix.user.id)
        if get_wallet(uid) < bet:
            await ix.response.send_message("❌ เงินไม่พอ", ephemeral=True); return
        choice_type = (self.f_type.value or "").strip().lower()
        if choice_type not in ("number","red","black","even","odd"):
            await ix.response.send_message("❌ ทายไม่ถูก", ephemeral=True); return
        choice_val = None
        if choice_type == "number":
            choice_val = _parse_int(self.f_val.value, -1)
            if choice_val is None or not 0 <= choice_val <= 36:
                await ix.response.send_message("❌ number ต้อง 0-36", ephemeral=True); return
        add_money(uid, -bet)
        room["players"].append({
            "uid": uid,
            "bet": bet,
            "choice": choice_type,
            "choice_val": choice_val,
        })
        save_rooms(rooms)
        await ix.response.send_message(
            content=f"✅ <@{uid}> เข้าห้อง `{self.rid}` แล้ว — เดิมพัน {money_str(bet)} ทาย `{choice_type}={choice_val}`",
            embed=_room_embed(self.rid, room),
            ephemeral=False,
        )


async def _spin_roulette_room(ix: discord.Interaction, rid: str):
    rooms = load_rooms()
    room = rooms.get(rid)
    if not room: return
    room["status"] = "playing"
    save_rooms(rooms)
    roll = _rand.randint(0, 36)
    reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    color_of = "red" if roll in reds else ("black" if roll != 0 else "green")

    # คำนวณผลแต่ละคน
    lines = []
    total_paid = 0
    for p in room["players"]:
        ct = p["choice"]
        cv = p["choice_val"]
        bet = int(p["bet"])
        won = False
        payout = 0
        if ct == "number":
            won = (roll == cv); payout = bet * 35 if won else 0
        elif ct in ("red","black"):
            won = (color_of == ct); payout = bet * 2 if won else 0
        elif ct in ("even","odd"):
            if roll != 0:
                won = (roll % 2 == 0 and ct == "even") or (roll % 2 == 1 and ct == "odd")
            payout = bet * 2 if won else 0
        if won:
            add_money(p["uid"], payout)
            total_paid += payout
            lines.append(f"🎉 <@{p['uid']}> · ทาย `{ct}={cv}` · เดิมพัน {bet:,} · **ชนะ {payout:,}**")
        else:
            lines.append(f"💔 <@{p['uid']}> · ทาย `{ct}={cv}` · เดิมพัน {bet:,} · **เสีย {bet:,}**")

    room["status"] = "closed"
    save_rooms(rooms)
    embed = discord.Embed(
        title=f"🎰 Roulette Result · `{rid}`",
        description=(
            f"**ลูกบอลตก:** **{roll}** ({color_of.upper()})\n\n"
            + "\n".join(lines) + "\n\n"
            f"_จ่ายรวม_  {total_paid:,}"
        ),
        color=0x2ecc71 if total_paid > 0 else 0xe74c3c,
    )
    await ix.response.send_message(embed=embed, ephemeral=False)


class CasinoRoomListSelect(discord.ui.Select):
    def __init__(self):
        rooms = load_rooms()
        open_rooms = [(rid, r) for rid, r in rooms.items() if r.get("status") == "open"]
        options = []
        for rid, r in open_rooms[:25]:
            options.append(discord.SelectOption(
                label=f"Room `{rid}` · {len(r.get('players',[]))}/{r['max_players']}"[:100],
                value=rid,
                description=f"Bet {r['min_bet']:,}-{r['max_bet']:,}"[:80],
            ))
        if not options:
            options = [discord.SelectOption(label="ไม่มีห้องเปิด", value="none")]
        super().__init__(placeholder="เลือกห้องที่จะเข้า...", options=options)

    async def callback(self, ix):
        if self.values[0] == "none":
            await ix.response.defer(); return
        rid = self.values[0]
        room = load_rooms().get(rid)
        if not room:
            await ix.response.send_message("❌ ไม่พบห้อง", ephemeral=True); return
        await ix.response.send_message(
            embed=_room_embed(rid, room),
            view=RoomJoinView(rid),
            ephemeral=False,
        )


# ════════════════════════════════════════════════════════════
# Main views
# ════════════════════════════════════════════════════════════

class CasinoMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=0)
    async def done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="Coinflip", style=discord.ButtonStyle.primary, row=1)
    async def b1(self, ix, _b):
        embed = make_menu_embed(
            "🪙 Coinflip",
            [("วิธีเล่น", "เลือก Heads หรือ Tails → วางเดิมพัน → ลุ้นออก 50/50 · ชนะได้ 1.95x")],
            color=0xf39c12,
        )
        await ix.response.send_message(embed=embed, view=CoinflipPickView(), ephemeral=True)

    @discord.ui.button(label="Dice", style=discord.ButtonStyle.primary, row=2)
    async def b2(self, ix, _b):
        embed = make_menu_embed(
            "🎲 Dice",
            [("วิธีเล่น", "ทายเลข 1-6 → วางเดิมพัน → ชนะได้ ×5")],
            color=0xf39c12,
        )
        view = discord.ui.View(timeout=120)

        class _OpenBet(discord.ui.Button):
            def __init__(s):
                super().__init__(label="เริ่มเล่น", style=discord.ButtonStyle.success)
            async def callback(s, ix2):
                await ix2.response.send_modal(DiceBetModal())
        view.add_item(_OpenBet())
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="Higher / Lower", style=discord.ButtonStyle.primary, row=3)
    async def b3(self, ix, _b):
        v = HiLoStartView()
        embed = make_menu_embed(
            "📈 Higher / Lower",
            [(f"การ์ดแรก: {v.first}", "ทายว่าการ์ดถัดไปจะสูงหรือต่ำกว่า · ชนะได้ 1.95x")],
            color=0xf39c12,
        )
        await ix.response.send_message(embed=embed, view=v, ephemeral=True)

    @discord.ui.button(label="Roulette", style=discord.ButtonStyle.primary, row=4)
    async def b4(self, ix, _b):
        embed = make_menu_embed(
            "🎰 Roulette",
            [
                ("เลือกประเภทเดิมพัน", "ทายเลข (×35) · สี แดง/ดำ (×2) · คู่/คี่ (×2)"),
                ("Multi-player", "ใช้ `/คาสิโนห้อง` สร้าง/เข้าห้องเล่นกับผู้เล่นคนอื่น"),
            ],
            color=0xf39c12,
        )
        await ix.response.send_message(embed=embed, view=RoulettePickView(), ephemeral=True)


# ════════════════════════════════════════════════════════════
# ADMIN PANEL — ปรับความยาก/อัตรา/เปิดปิดเกม
# ════════════════════════════════════════════════════════════

def _admin_overview_embed() -> discord.Embed:
    cfg = load_casino_cfg()
    games = cfg.get("games", {})
    sections = [
        f"_เดิมพัน_  `{cfg['global_min_bet']:,}` — `{cfg['global_max_bet']:,}`",
    ]
    for key, label in [("coinflip","🪙 Coinflip"), ("dice","🎲 Dice"), ("hilo","📈 Higher/Lower"), ("roulette","🎰 Roulette")]:
        g = games.get(key, {})
        status = "🟢 เปิด" if g.get("enabled", True) else "🔴 ปิด"
        if key == "roulette":
            payout_str = f"number ×{g.get('number_payout_x',35)} · color ×{g.get('color_payout_x',2)} · even/odd ×{g.get('evenodd_payout_x',2)}"
        else:
            payout_str = f"payout ×{g.get('payout_x','?')}"
        bonus = int(g.get("win_chance_bonus", 0))
        bonus_str = (f"+{bonus}%" if bonus > 0 else f"{bonus}%") + " (โอกาสชนะ)"
        sections.append((
            label,
            f"{status}  ·  {payout_str}  ·  {bonus_str}"
        ))
    return make_menu_embed("Casino Admin", sections, color=0xf39c12)


class CasinoBetLimitModal(discord.ui.Modal, title="ตั้งช่วงเดิมพันรวม"):
    f_min = discord.ui.TextInput(label="เดิมพันขั้นต่ำ", placeholder="1", max_length=10)
    f_max = discord.ui.TextInput(label="เดิมพันสูงสุด", placeholder="100000", max_length=12)

    def __init__(self):
        super().__init__()
        cfg = load_casino_cfg()
        self.f_min.default = str(cfg["global_min_bet"])
        self.f_max.default = str(cfg["global_max_bet"])

    async def on_submit(self, ix):
        cfg = load_casino_cfg()
        cfg["global_min_bet"] = max(1, _parse_int(self.f_min.value, 1) or 1)
        cfg["global_max_bet"] = max(cfg["global_min_bet"], _parse_int(self.f_max.value, 100000) or 100000)
        save_casino_cfg(cfg)
        await ix.response.send_message(
            f"✅ เดิมพัน {cfg['global_min_bet']:,} — {cfg['global_max_bet']:,}",
            ephemeral=True,
        )


class GameTuneModal(discord.ui.Modal):
    f_payout = discord.ui.TextInput(label="Payout multiplier (x)", placeholder="1.95")
    f_bonus  = discord.ui.TextInput(label="Win chance bonus (% ±100)", placeholder="0")
    f_extra  = discord.ui.TextInput(label="Roulette: color, even/odd payout (คั่น ,)", required=False, placeholder="2, 2")

    def __init__(self, game_key: str):
        super().__init__(title=f"ปรับเกม {game_key}")
        self.game_key = game_key
        cfg = load_casino_cfg()
        g = cfg["games"][game_key]
        if game_key == "roulette":
            self.f_payout.default = str(g.get("number_payout_x", 35))
            self.f_extra.default  = f"{g.get('color_payout_x',2)}, {g.get('evenodd_payout_x',2)}"
        else:
            self.f_payout.default = str(g.get("payout_x", 1.95))
        self.f_bonus.default = str(g.get("win_chance_bonus", 0))

    async def on_submit(self, ix):
        cfg = load_casino_cfg()
        g = cfg["games"][self.game_key]
        try:
            payout = float(self.f_payout.value)
        except Exception:
            await ix.response.send_message("❌ payout ต้องเป็นตัวเลข", ephemeral=True); return
        bonus = _parse_int(self.f_bonus.value, 0) or 0
        bonus = max(-100, min(100, bonus))
        g["win_chance_bonus"] = bonus
        if self.game_key == "roulette":
            g["number_payout_x"] = payout
            parts = [p.strip() for p in (self.f_extra.value or "").split(",")]
            try:
                if len(parts) >= 1 and parts[0]: g["color_payout_x"]   = float(parts[0])
                if len(parts) >= 2 and parts[1]: g["evenodd_payout_x"] = float(parts[1])
            except Exception:
                pass
        else:
            g["payout_x"] = payout
        save_casino_cfg(cfg)
        await ix.response.send_message(f"✅ อัปเดตเกม {self.game_key} แล้ว", ephemeral=True)


class CasinoToggleSelect(discord.ui.Select):
    """multi-select toggle เปิดปิดเกม"""
    def __init__(self):
        cfg = load_casino_cfg()
        games = cfg.get("games", {})
        options = []
        for key, label in [("coinflip","Coinflip"), ("dice","Dice"), ("hilo","Higher/Lower"), ("roulette","Roulette")]:
            enabled = games.get(key, {}).get("enabled", True)
            options.append(discord.SelectOption(
                label=f"{label} — {'🟢' if enabled else '🔴'}",
                value=key,
                default=enabled,
            ))
        super().__init__(placeholder="ติ๊กเกมที่ต้องการให้เปิด", options=options, min_values=0, max_values=len(options))

    async def callback(self, ix: discord.Interaction):
        cfg = load_casino_cfg()
        enabled_set = set(self.values)
        for key in ("coinflip","dice","hilo","roulette"):
            cfg["games"][key]["enabled"] = (key in enabled_set)
        save_casino_cfg(cfg)
        await ix.response.edit_message(embed=_admin_overview_embed(), view=CasinoAdminView())


class GamePickForTuneSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Coinflip", value="coinflip"),
            discord.SelectOption(label="Dice",     value="dice"),
            discord.SelectOption(label="Higher / Lower", value="hilo"),
            discord.SelectOption(label="Roulette", value="roulette"),
        ]
        super().__init__(placeholder="เลือกเกมที่จะปรับ payout / win chance", options=options)

    async def callback(self, ix: discord.Interaction):
        await ix.response.send_modal(GameTuneModal(self.values[0]))


class CasinoAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(CasinoToggleSelect())
        self.add_item(GamePickForTuneSelect())

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=2)
    async def done(self, ix, _b):
        await ix.response.edit_message(content="✓", embed=None, view=None)

    @discord.ui.button(label="ตั้งช่วงเดิมพัน", style=discord.ButtonStyle.primary, row=3)
    async def b_bet(self, ix, _b):
        await ix.response.send_modal(CasinoBetLimitModal())

    @discord.ui.button(label="รีเซ็ตเป็นค่าเริ่มต้น", style=discord.ButtonStyle.danger, row=4)
    async def b_reset(self, ix, _b):
        save_casino_cfg(json.loads(json.dumps(DEFAULT_CASINO_CFG)))
        await ix.response.edit_message(embed=_admin_overview_embed(), view=CasinoAdminView())


@bot.tree.command(name="คาสิโนแอดมิน", description="[Admin] ควบคุมคาสิโน — ความยาก/payout/เปิดปิดเกม", guild=_ORION_GUILD_OBJ)
async def cmd_casino_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    await interaction.response.send_message(
        embed=_admin_overview_embed(),
        view=CasinoAdminView(),
        ephemeral=True,
    )


@bot.tree.command(name="คาสิโน", description="เล่นคาสิโน solo — Coinflip / Dice / Hi-Lo / Roulette", guild=_ORION_GUILD_OBJ)
async def cmd_casino(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    ensure_orion_player(str(interaction.user.id))
    embed = make_menu_embed(
        "Casino",
        [
            f"_เงินคุณ_  {money_str(get_wallet(str(interaction.user.id)))}",
            ("Coinflip", "Heads/Tails 50/50 · 1.95x"),
            ("Dice", "ทายเลข 1-6 · ×5"),
            ("Higher / Lower", "ทายการ์ดถัดไปสูง/ต่ำ · 1.95x"),
            ("Roulette", "เลข/สี/คู่คี่ · สูงสุด ×35"),
        ],
        color=0xf39c12,
    )
    await interaction.response.send_message(embed=embed, view=CasinoMainView(), ephemeral=_eph("คาสิโน"))


@bot.tree.command(name="คาสิโนห้อง", description="คาสิโนมัลติเพลย์เยอร์ — Roulette Room", guild=_ORION_GUILD_OBJ)
async def cmd_casino_rooms(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    open_rooms = [(rid, r) for rid, r in load_rooms().items() if r.get("status") == "open"]
    embed = make_menu_embed(
        "Casino Rooms (Roulette)",
        [
            f"_ห้องเปิดอยู่_  `{len(open_rooms)}` _ห้อง_",
            ("สร้างห้องใหม่", "ตั้งเดิมพันขั้นต่ำ/สูงสุด + ผู้เล่นสูงสุด — เป็น Owner กด Spin เอง"),
            ("เข้าห้อง", "เลือกห้องจาก dropdown → กด Join + Bet"),
        ],
        color=0x9b59b6,
    )
    view = discord.ui.View(timeout=300)

    class _Create(discord.ui.Button):
        def __init__(s):
            super().__init__(label="สร้างห้องใหม่", style=discord.ButtonStyle.success, row=0)
        async def callback(s, ix):
            await ix.response.send_modal(RoomCreateModal())
    view.add_item(_Create())
    view.add_item(CasinoRoomListSelect())
    await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
