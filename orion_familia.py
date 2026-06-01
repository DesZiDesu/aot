# ============================================================
# ORION — Familia System (separate module)
# ============================================================
# Familia เหมือนกิลด์เวอร์ชั่นที่เข้มข้นกว่า:
#   - Admin ตั้งได้ว่า Discord role ไหนสามารถ "สร้าง" Familia ได้
#   - หัวหน้า (เทพ) เชิญ/ไล่/แต่งตั้ง/ปลด
#   - Passive income: ทุก N นาที สมาชิกได้เงินอัตโนมัติ
#     (modes: distribute = ทุกคนได้, leader = เทพได้คนเดียว มีปุ่มแบ่ง)
#   - Minigame mode (optional): หัวหน้ากดปุ่ม → เล่นมินิเกม → ได้เงินเข้า treasury
# ============================================================

import sys
import time
import datetime
import uuid as _uuid
import discord
from discord.ext import tasks

# ── dependencies ──────────────────────────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_familia ต้องถูก import จาก orion_bot.py")

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
load_currency_cfg    = _orion_bot_mod.load_currency_cfg
money_str            = _orion_bot_mod.money_str
get_wallet           = _orion_bot_mod.get_wallet
add_money            = _orion_bot_mod.add_money
_parse_int           = _orion_bot_mod._parse_int
_run_minigame        = _orion_bot_mod._run_minigame
MINIGAME_LABELS      = _orion_bot_mod.MINIGAME_LABELS


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


FAMILIA_FILE     = f"{ORION_DATA_DIR}/familias.json"
FAMILIA_CFG_FILE = f"{ORION_DATA_DIR}/familia_config.json"

DEFAULT_FAMILIA_CFG = {
    "allowed_role_ids": [],          # Discord role IDs ที่สร้าง Familia ได้ (ว่าง = แอดมินเท่านั้น)
    "passive_amount":  10,           # เงิน passive income ต่อรอบ
    "passive_interval_min": 60,      # นาที
    "passive_mode": "leader",        # "distribute" หรือ "leader"
    "minigame_amount": 50,           # เงินจากมินิเกม (ต่อครั้ง)
    "minigame_keys": ["guess_number"],  # subset ของ MINIGAME_KEYS
    "max_members": 20,
}

RANK_LABEL = {"leader": "👑 เทพ", "officer": "⚔️ ผู้ช่วย", "member": "🛡️ สมาชิก"}
RANK_ORDER = {"leader": 0, "officer": 1, "member": 2}


# ── Storage ──────────────────────────────────────────────────
def load_familia_cfg() -> dict:
    cfg = load_json(FAMILIA_CFG_FILE, {})
    changed = False
    for k, v in DEFAULT_FAMILIA_CFG.items():
        if k not in cfg:
            cfg[k] = v; changed = True
    if changed:
        save_familia_cfg(cfg)
    return cfg


def save_familia_cfg(cfg: dict):
    save_json(FAMILIA_CFG_FILE, cfg)


def load_familias() -> dict:
    return load_json(FAMILIA_FILE, {})


def save_familias(d: dict):
    save_json(FAMILIA_FILE, d)


def get_player_familia(uid: str):
    fams = load_familias()
    for fid, f in fams.items():
        for m in f.get("members", []):
            if m.get("uid") == uid:
                return fid, f
    return None


def member_rank(f: dict, uid: str) -> str:
    for m in f.get("members", []):
        if m.get("uid") == uid:
            return m.get("rank", "member")
    return ""


def can_create_familia(member: discord.Member) -> bool:
    """check ว่าผู้ใช้สร้าง Familia ได้มั้ย — admin หรือมี role ที่อนุญาต"""
    if member.guild_permissions.administrator:
        return True
    cfg = load_familia_cfg()
    allowed = set(cfg.get("allowed_role_ids", []))
    if not allowed:
        return False
    user_role_ids = {r.id for r in member.roles}
    return bool(user_role_ids & allowed)


# ── Embed ────────────────────────────────────────────────────
def _familia_embed(fid: str, f: dict) -> discord.Embed:
    cfg = load_familia_cfg()
    cur_cfg = load_currency_cfg()
    embed = discord.Embed(
        title=f"Familia · {f.get('name','?')}",
        description=f.get("description") or "_— ไม่มีคำอธิบาย —_",
        color=0xc0392b,
    )
    if f.get("image_url"):
        embed.set_thumbnail(url=f["image_url"])
    members = sorted(f.get("members", []), key=lambda m: RANK_ORDER.get(m.get("rank","member"), 9))
    lines = [f"{RANK_LABEL.get(m.get('rank','member'),'')} <@{m['uid']}>" for m in members[:25]]
    embed.add_field(name=f"สมาชิก `{len(members)}/{cfg.get('max_members',20)}`",
                    value="\n".join(lines) or "_ว่าง_", inline=False)
    if cfg.get("passive_mode") == "leader":
        embed.add_field(name="คลัง",
                        value=f"{cur_cfg['emoji']} **{int(f.get('treasury',0)):,}**",
                        inline=True)
    embed.add_field(
        name="Passive",
        value=(
            f"`{cfg['passive_amount']:,}` ทุก `{cfg['passive_interval_min']}` นาที\n"
            f"_โหมด · {'แจกทุกคน' if cfg['passive_mode']=='distribute' else 'เข้าคลัง'}_"
        ),
        inline=True,
    )
    embed.set_footer(text=f"ID: {fid}")
    return embed


# ── Player flow ──────────────────────────────────────────────
class FamiliaCreateModal(discord.ui.Modal, title="⚜️ สร้าง Familia ใหม่"):
    f_name  = discord.ui.TextInput(label="ชื่อ Familia", max_length=50)
    f_desc  = discord.ui.TextInput(label="คำขวัญ / คำอธิบาย", style=discord.TextStyle.paragraph, required=False, max_length=400)
    f_image = discord.ui.TextInput(label="URL รูป (ไม่บังคับ)", required=False, max_length=400)

    async def on_submit(self, ix: discord.Interaction):
        member = ix.user
        if not can_create_familia(member):
            await ix.response.send_message("❌ คุณไม่มีสิทธิ์สร้าง Familia (role ไม่ตรง)", ephemeral=True); return
        uid = str(member.id)
        if get_player_familia(uid) is not None:
            await ix.response.send_message("❌ คุณอยู่ใน Familia อยู่แล้ว", ephemeral=True); return
        cfg = load_familia_cfg()
        fid = _uuid.uuid4().hex[:8]
        fams = load_familias()
        fams[fid] = {
            "name": self.f_name.value.strip(),
            "description": (self.f_desc.value or "").strip(),
            "image_url":   (self.f_image.value or "").strip(),
            "leader_id":   uid,
            "members":     [{"uid": uid, "rank": "leader"}],
            "treasury":    0,
            "last_payout": int(time.time()),
            "created_at":  datetime.datetime.utcnow().strftime("%Y-%m-%d"),
            "invites":     [],
        }
        save_familias(fams)
        ensure_orion_player(uid)
        await ix.response.send_message(
            f"✅ สร้าง Familia **{fams[fid]['name']}** สำเร็จ!",
            embed=_familia_embed(fid, fams[fid]),
            view=FamiliaPanelView(fid, uid),
            ephemeral=True,
        )


class FamiliaInviteUserSelect(discord.ui.UserSelect):
    def __init__(self, fid: str):
        super().__init__(placeholder="📨 เลือกคนที่จะเชิญ...", min_values=1, max_values=1)
        self.fid = fid

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.bot:
            await ix.response.send_message("❌ ชวนบอทไม่ได้", ephemeral=True); return
        fams = load_familias()
        f = fams.get(self.fid)
        if not f:
            await ix.response.send_message("❌ ไม่พบ Familia", ephemeral=True); return
        if get_player_familia(str(target.id)) is not None:
            await ix.response.send_message("❌ เขาอยู่ Familia อื่นแล้ว", ephemeral=True); return
        cfg = load_familia_cfg()
        if len(f.get("members", [])) >= cfg.get("max_members", 20):
            await ix.response.send_message("❌ Familia เต็มแล้ว", ephemeral=True); return
        f.setdefault("invites", [])
        if str(target.id) in f["invites"]:
            await ix.response.send_message("⚠️ ส่งคำเชิญไปแล้ว", ephemeral=True); return
        f["invites"].append(str(target.id))
        save_familias(fams)
        # respond first ก่อน เพื่อกัน interaction expire (10062)
        await ix.response.send_message(f"✅ ส่งคำเชิญถึง {target.mention} แล้ว", ephemeral=True)
        # DM หลังจากนั้น (fire-and-forget)
        try:
            await target.send(f"⚜️ คุณได้รับคำเชิญเข้า Familia **{f['name']}** — ใช้ `/familia` ใน Orion เพื่อกดรับ")
        except Exception:
            pass


class FamiliaInviteView(discord.ui.View):
    def __init__(self, fid: str):
        super().__init__(timeout=180)
        self.add_item(FamiliaInviteUserSelect(fid))


class FamiliaMemberSelect(discord.ui.Select):
    """dropdown สมาชิก (ยกเว้น leader) สำหรับ promote/kick"""
    def __init__(self, fid: str, action: str):
        self.fid = fid
        self.action = action
        f = load_familias().get(fid, {})
        options = []
        for m in f.get("members", []):
            if m.get("rank") == "leader":
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
        super().__init__(placeholder=f"เลือกสมาชิก... ({action})", options=options)

    async def callback(self, ix: discord.Interaction):
        uid = self.values[0]
        if uid == "none":
            await ix.response.defer(); return
        fams = load_familias()
        f = fams.get(self.fid)
        if not f:
            await ix.response.send_message("❌ ไม่พบ Familia", ephemeral=True); return
        m = next((x for x in f.get("members", []) if x["uid"] == uid), None)
        if not m:
            await ix.response.send_message("❌ ไม่ใช่สมาชิก", ephemeral=True); return
        if self.action == "kick":
            f["members"].remove(m)
            save_familias(fams)
            await ix.response.edit_message(content=f"🚪 เตะ <@{uid}> ออกจาก Familia แล้ว", view=None)
        elif self.action == "promote":
            await ix.response.edit_message(content=f"⚔️ เลือกตำแหน่งใหม่ของ <@{uid}> ↓", view=FamiliaRankPickerView(self.fid, uid))


class FamiliaKickView(discord.ui.View):
    def __init__(self, fid: str):
        super().__init__(timeout=180)
        self.add_item(FamiliaMemberSelect(fid, "kick"))


class FamiliaPromoteView(discord.ui.View):
    def __init__(self, fid: str):
        super().__init__(timeout=180)
        self.add_item(FamiliaMemberSelect(fid, "promote"))


class FamiliaRankPickerView(discord.ui.View):
    def __init__(self, fid: str, target_uid: str):
        super().__init__(timeout=120)
        self.fid = fid
        self.target_uid = target_uid

    async def _set(self, ix, rank: str):
        fams = load_familias()
        f = fams.get(self.fid)
        if not f:
            await ix.response.send_message("❌ ไม่พบ Familia", ephemeral=True); return
        m = next((x for x in f.get("members", []) if x["uid"] == self.target_uid), None)
        if not m or m.get("rank") == "leader":
            await ix.response.send_message("❌ เปลี่ยนตำแหน่งไม่ได้", ephemeral=True); return
        m["rank"] = rank
        save_familias(fams)
        await ix.response.edit_message(content=f"✅ <@{self.target_uid}> → **{RANK_LABEL.get(rank)}**", view=None)

    @discord.ui.button(label="ผู้ช่วย", style=discord.ButtonStyle.primary)
    async def b1(self, ix, _b): await self._set(ix, "officer")

    @discord.ui.button(label="สมาชิก", style=discord.ButtonStyle.secondary)
    async def b2(self, ix, _b): await self._set(ix, "member")


# ── Distribute treasury (เทพแบ่งเงินให้สมาชิก) ─────────────
class DistributeConfirmView(discord.ui.View):
    def __init__(self, fid: str):
        super().__init__(timeout=60)
        self.fid = fid

    @discord.ui.button(label="ยืนยันแบ่ง", style=discord.ButtonStyle.success)
    async def btn_yes(self, ix: discord.Interaction, _b):
        fams = load_familias()
        f = fams.get(self.fid)
        if not f:
            await ix.response.edit_message(content="❌ ไม่พบ Familia", view=None); return
        treasury = int(f.get("treasury", 0))
        members = f.get("members", [])
        if not members or treasury <= 0:
            await ix.response.edit_message(content="❌ ไม่มีเงินในคลัง หรือไม่มีสมาชิก", view=None); return
        share = treasury // len(members)
        if share <= 0:
            await ix.response.edit_message(content=f"❌ เงินน้อยเกิน ({treasury}/{len(members)} = 0 ต่อคน)", view=None); return
        for m in members:
            add_money(m["uid"], share)
        f["treasury"] = treasury - share * len(members)
        save_familias(fams)
        await ix.response.edit_message(
            content=f"💸 แบ่ง {money_str(share)} ให้สมาชิก {len(members)} คน (รวม {money_str(share * len(members))})",
            view=None,
        )

    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def btn_no(self, ix, _b):
        await ix.response.edit_message(content="❌ ยกเลิก", view=None)


# ── Minigame to earn (leader-only) ───────────────────────────
class FamiliaMinigameSelect(discord.ui.Select):
    def __init__(self, fid: str):
        self.fid = fid
        cfg = load_familia_cfg()
        keys = cfg.get("minigame_keys", [])
        if not keys:
            keys = list(MINIGAME_LABELS.keys())[:5]
        options = [discord.SelectOption(label=MINIGAME_LABELS.get(k, k)[:100], value=k) for k in keys[:25]]
        super().__init__(placeholder="🎮 เลือกมินิเกมเพื่อหาเงิน...", options=options)

    async def callback(self, ix: discord.Interaction):
        mg = self.values[0]
        cfg = load_familia_cfg()
        await ix.response.defer(ephemeral=True)
        ok = await _run_minigame(ix, mg)
        if not ok:
            await ix.followup.send("💔 มินิเกมล้มเหลว — ไม่ได้เงิน", ephemeral=True); return
        fams = load_familias()
        f = fams.get(self.fid)
        if not f:
            await ix.followup.send("❌ ไม่พบ Familia", ephemeral=True); return
        amount = int(cfg.get("minigame_amount", 50))
        if cfg.get("passive_mode") == "leader":
            f["treasury"] = int(f.get("treasury", 0)) + amount
            save_familias(fams)
            await ix.followup.send(f"🎉 ได้ {money_str(amount)} เข้าคลัง Familia (ตอนนี้ {money_str(f['treasury'])})", ephemeral=True)
        else:
            members = f.get("members", [])
            share = amount // max(1, len(members))
            for m in members:
                add_money(m["uid"], share)
            await ix.followup.send(f"🎉 ได้ {money_str(amount)} แบ่งให้สมาชิก {len(members)} คน ({share}/คน)", ephemeral=True)


class FamiliaMinigameView(discord.ui.View):
    def __init__(self, fid: str):
        super().__init__(timeout=180)
        self.add_item(FamiliaMinigameSelect(fid))


# ── Panel buttons ────────────────────────────────────────────
class FamiliaPanelView(discord.ui.View):
    def __init__(self, fid: str, viewer_uid: str):
        super().__init__(timeout=300)
        self.fid = fid
        self.viewer_uid = viewer_uid
        f = load_familias().get(fid, {})
        my_rank = member_rank(f, viewer_uid)
        is_leader = my_rank == "leader"
        is_officer = my_rank in ("leader", "officer")
        if is_officer:
            self.add_item(FamInviteBtn(fid))
        if is_leader:
            self.add_item(FamPromoteBtn(fid))
            self.add_item(FamKickBtn(fid))
            self.add_item(FamMinigameBtn(fid))
            cfg = load_familia_cfg()
            if cfg.get("passive_mode") == "leader":
                self.add_item(FamDistributeBtn(fid))
            self.add_item(FamDisbandBtn(fid))
        self.add_item(FamLeaveBtn(fid, viewer_uid))


class FamInviteBtn(discord.ui.Button):
    def __init__(self, fid):
        super().__init__(label="เชิญสมาชิก", style=discord.ButtonStyle.success, row=0)
        self.fid = fid
    async def callback(self, ix):
        await ix.response.send_message("📨 เลือกผู้เล่น ↓", view=FamiliaInviteView(self.fid), ephemeral=True)


class FamPromoteBtn(discord.ui.Button):
    def __init__(self, fid):
        super().__init__(label="แต่งตั้ง/ปลด", style=discord.ButtonStyle.primary, row=0)
        self.fid = fid
    async def callback(self, ix):
        await ix.response.send_message("⚔️ เลือกสมาชิก ↓", view=FamiliaPromoteView(self.fid), ephemeral=True)


class FamKickBtn(discord.ui.Button):
    def __init__(self, fid):
        super().__init__(label="เตะสมาชิก", style=discord.ButtonStyle.secondary, row=0)
        self.fid = fid
    async def callback(self, ix):
        await ix.response.send_message("🚪 เลือกสมาชิก ↓", view=FamiliaKickView(self.fid), ephemeral=True)


class FamMinigameBtn(discord.ui.Button):
    def __init__(self, fid):
        super().__init__(label="เล่นมินิเกมหาเงิน", style=discord.ButtonStyle.success, row=1)
        self.fid = fid
    async def callback(self, ix):
        await ix.response.send_message("🎮 เลือกมินิเกม ↓", view=FamiliaMinigameView(self.fid), ephemeral=True)


class FamDistributeBtn(discord.ui.Button):
    def __init__(self, fid):
        super().__init__(label="แบ่งเงินจากคลัง", style=discord.ButtonStyle.primary, row=1)
        self.fid = fid
    async def callback(self, ix):
        f = load_familias().get(self.fid, {})
        t = int(f.get("treasury", 0))
        await ix.response.send_message(
            f"💸 คลังมี {money_str(t)} — แบ่งเท่ากันให้สมาชิก {len(f.get('members',[]))} คน?",
            view=DistributeConfirmView(self.fid),
            ephemeral=True,
        )


class FamDisbandBtn(discord.ui.Button):
    def __init__(self, fid):
        super().__init__(label="ยุบ Familia", style=discord.ButtonStyle.danger, row=2)
        self.fid = fid
    async def callback(self, ix):
        view = FamDisbandConfirmView(self.fid)
        await ix.response.send_message("⚠️ **ยุบ Familia ถาวร?**", view=view, ephemeral=True)


class FamDisbandConfirmView(discord.ui.View):
    def __init__(self, fid):
        super().__init__(timeout=60)
        self.fid = fid
    @discord.ui.button(label="ยืนยันยุบ", style=discord.ButtonStyle.danger)
    async def btn_yes(self, ix, _b):
        fams = load_familias()
        f = fams.pop(self.fid, None)
        save_familias(fams)
        await ix.response.edit_message(content=f"💥 ยุบ **{f.get('name') if f else '?'}** แล้ว", view=None)
    @discord.ui.button(label="ยกเลิก", style=discord.ButtonStyle.secondary)
    async def btn_no(self, ix, _b):
        await ix.response.edit_message(content="❌ ยกเลิก", view=None)


class FamLeaveBtn(discord.ui.Button):
    def __init__(self, fid, uid):
        super().__init__(label="ออกจาก Familia", emoji="👋", style=discord.ButtonStyle.danger, row=2)
        self.fid = fid; self.uid = uid
    async def callback(self, ix):
        fams = load_familias()
        f = fams.get(self.fid)
        if not f:
            await ix.response.send_message("❌ ไม่พบ Familia", ephemeral=True); return
        m = next((x for x in f.get("members", []) if x["uid"] == self.uid), None)
        if not m:
            await ix.response.send_message("❌ ไม่ใช่สมาชิก", ephemeral=True); return
        if m.get("rank") == "leader":
            await ix.response.send_message("❌ เทพออกเองไม่ได้ — ใช้ปุ่มยุบ", ephemeral=True); return
        f["members"].remove(m)
        save_familias(fams)
        await ix.response.send_message(f"👋 ออกจาก **{f.get('name')}** แล้ว", ephemeral=True)


# ── Entry view (ยังไม่อยู่ Familia) ──────────────────────────
class FamiliaEntryView(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=180)
        self.uid = uid
        invites = [(fid, f) for fid, f in load_familias().items() if uid in f.get("invites", [])]
        if invites:
            self.add_item(FamAcceptInviteSelect(uid, invites))

    @discord.ui.button(label="สร้าง Familia ใหม่", style=discord.ButtonStyle.success)
    async def btn_create(self, ix, _b):
        if not can_create_familia(ix.user):
            await ix.response.send_message("❌ คุณไม่มี role ที่อนุญาตให้สร้าง Familia", ephemeral=True); return
        await ix.response.send_modal(FamiliaCreateModal())


class FamAcceptInviteSelect(discord.ui.Select):
    def __init__(self, uid: str, invites: list):
        self.uid = uid
        options = []
        for fid, f in invites[:25]:
            options.append(discord.SelectOption(
                label=f.get("name","?")[:100],
                value=fid,
                description=f"สมาชิก {len(f.get('members',[]))}"[:80],
            ))
        super().__init__(placeholder="📨 รับคำเชิญ...", options=options)

    async def callback(self, ix: discord.Interaction):
        fid = self.values[0]
        fams = load_familias()
        f = fams.get(fid)
        if not f or self.uid not in f.get("invites", []):
            await ix.response.send_message("❌ คำเชิญหมดอายุ", ephemeral=True); return
        cfg = load_familia_cfg()
        if len(f.get("members", [])) >= cfg.get("max_members", 20):
            await ix.response.send_message("❌ Familia เต็ม", ephemeral=True); return
        if get_player_familia(self.uid) is not None:
            await ix.response.send_message("❌ คุณอยู่ Familia อื่นแล้ว", ephemeral=True); return
        f["invites"].remove(self.uid)
        f.setdefault("members", []).append({"uid": self.uid, "rank": "member"})
        save_familias(fams)
        await ix.response.send_message(
            f"✅ เข้าร่วม **{f['name']}** สำเร็จ!",
            embed=_familia_embed(fid, f),
            view=FamiliaPanelView(fid, self.uid),
            ephemeral=True,
        )


# ── Admin Panel ──────────────────────────────────────────────
class FamiliaAdminRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="เลือก Discord role ที่สร้าง Familia ได้...", min_values=0, max_values=10)

    async def callback(self, ix: discord.Interaction):
        cfg = load_familia_cfg()
        cfg["allowed_role_ids"] = [r.id for r in self.values]
        save_familia_cfg(cfg)
        names = ", ".join(r.mention for r in self.values) or "_(ว่าง — เฉพาะ admin)_"
        await ix.response.send_message(f"✅ ตั้ง role ที่สร้าง Familia ได้: {names}", ephemeral=True)


class FamiliaAdminRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(FamiliaAdminRoleSelect())


class FamiliaSettingsModal(discord.ui.Modal, title="⚙️ ตั้งค่า Familia"):
    f_passive_amt   = discord.ui.TextInput(label="เงิน passive ต่อรอบ", placeholder="10", max_length=8)
    f_passive_int   = discord.ui.TextInput(label="ระยะเวลา passive (นาที)", placeholder="60", max_length=6)
    f_passive_mode  = discord.ui.TextInput(label="โหมด (distribute หรือ leader)", placeholder="leader", max_length=15)
    f_mg_amount     = discord.ui.TextInput(label="เงินจากมินิเกม / รอบ", placeholder="50", max_length=8)
    f_max_members   = discord.ui.TextInput(label="สมาชิกสูงสุด", placeholder="20", max_length=4)

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_familia_cfg()
        cfg["passive_amount"]      = max(0, _parse_int(self.f_passive_amt.value, 10) or 10)
        cfg["passive_interval_min"]= max(1, _parse_int(self.f_passive_int.value, 60) or 60)
        mode = (self.f_passive_mode.value or "leader").strip().lower()
        cfg["passive_mode"] = mode if mode in ("distribute", "leader") else "leader"
        cfg["minigame_amount"]     = max(0, _parse_int(self.f_mg_amount.value, 50) or 50)
        cfg["max_members"]         = max(1, _parse_int(self.f_max_members.value, 20) or 20)
        save_familia_cfg(cfg)
        await ix.response.send_message(
            f"✅ ตั้งค่า Familia แล้ว — passive {cfg['passive_amount']}/{cfg['passive_interval_min']}min "
            f"โหมด **{cfg['passive_mode']}** · max {cfg['max_members']}",
            ephemeral=True,
        )


class FamiliaMinigamePickerSelect(discord.ui.Select):
    def __init__(self):
        cfg = load_familia_cfg()
        active = set(cfg.get("minigame_keys", []))
        options = []
        for key, label in MINIGAME_LABELS.items():
            options.append(discord.SelectOption(label=label[:100], value=key, default=(key in active)))
        super().__init__(placeholder="🎮 ติ๊กมินิเกมที่ Familia ใช้หาเงินได้...", options=options, min_values=0, max_values=len(options))

    async def callback(self, ix: discord.Interaction):
        cfg = load_familia_cfg()
        cfg["minigame_keys"] = list(self.values)
        save_familia_cfg(cfg)
        await ix.response.send_message(f"✅ ตั้งมินิเกม Familia: {len(cfg['minigame_keys'])} อัน", ephemeral=True)


class FamiliaMinigamePickerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(FamiliaMinigamePickerSelect())


class FamiliaAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ตั้งค่าทั่วไป", style=discord.ButtonStyle.primary, row=0)
    async def btn_set(self, ix, _b):
        cfg = load_familia_cfg()
        modal = FamiliaSettingsModal()
        modal.f_passive_amt.default  = str(cfg["passive_amount"])
        modal.f_passive_int.default  = str(cfg["passive_interval_min"])
        modal.f_passive_mode.default = cfg["passive_mode"]
        modal.f_mg_amount.default    = str(cfg["minigame_amount"])
        modal.f_max_members.default  = str(cfg["max_members"])
        await ix.response.send_modal(modal)

    @discord.ui.button(label="ตั้ง Role สร้างได้", style=discord.ButtonStyle.primary, row=0)
    async def btn_role(self, ix, _b):
        await ix.response.send_message(
            "🛡️ เลือก Discord role ที่อนุญาตให้สร้าง Familia (ว่าง = admin เท่านั้น) ↓",
            view=FamiliaAdminRoleView(), ephemeral=True,
        )

    @discord.ui.button(label="ตั้งมินิเกมหาเงิน", style=discord.ButtonStyle.primary, row=0)
    async def btn_mg(self, ix, _b):
        await ix.response.send_message(
            "🎮 ติ๊กมินิเกมที่ leader จะใช้หาเงินได้ ↓",
            view=FamiliaMinigamePickerView(), ephemeral=True,
        )

    @discord.ui.button(label="ดู Familia ทั้งหมด", style=discord.ButtonStyle.secondary, row=1)
    async def btn_list(self, ix, _b):
        fams = load_familias()
        if not fams:
            await ix.response.send_message("_ยังไม่มี Familia_", ephemeral=True); return
        lines = []
        for fid, f in list(fams.items())[:20]:
            lines.append(f"⚜️ **{f.get('name','?')}** — เทพ <@{f.get('leader_id','?')}> · สมาชิก {len(f.get('members',[]))}")
        embed = discord.Embed(title=f"📚 Familia ทั้งหมด ({len(fams)})", description="\n".join(lines), color=0xc0392b)
        await ix.response.send_message(embed=embed, ephemeral=True)


# ── Passive income loop ──────────────────────────────────────
@tasks.loop(minutes=1)
async def familia_passive_loop():
    try:
        cfg = load_familia_cfg()
        amt = int(cfg.get("passive_amount", 0))
        interval = max(1, int(cfg.get("passive_interval_min", 60)))
        mode = cfg.get("passive_mode", "leader")
        if amt <= 0:
            return
        now = int(time.time())
        threshold = interval * 60
        fams = load_familias()
        changed = False
        for fid, f in fams.items():
            last = int(f.get("last_payout", 0))
            if now - last < threshold:
                continue
            members = f.get("members", [])
            if not members:
                continue
            if mode == "distribute":
                for m in members:
                    add_money(m["uid"], amt)
            else:   # leader → treasury
                f["treasury"] = int(f.get("treasury", 0)) + amt
            f["last_payout"] = now
            changed = True
        if changed:
            save_familias(fams)
    except Exception as e:
        print(f"[familia_passive_loop] {e}")


@familia_passive_loop.before_loop
async def _wait_ready():
    await bot.wait_until_ready()


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="familia", description="ระบบ Familia — สร้าง/ดู/จัดการ", guild=_ORION_GUILD_OBJ)
async def cmd_familia(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    uid = str(interaction.user.id)
    info = get_player_familia(uid)
    eph = _eph("familia")
    if info:
        fid, f = info
        await interaction.response.send_message(
            embed=_familia_embed(fid, f),
            view=FamiliaPanelView(fid, uid),
            ephemeral=eph,
        )
    else:
        cfg = load_familia_cfg()
        invites = [f for fid, f in load_familias().items() if uid in f.get("invites", [])]
        can_create = can_create_familia(interaction.user)
        embed = discord.Embed(
            title="Familia — Main Menu",
            description=(
                f"_คุณยังไม่อยู่ Familia ใด_\n\n"
                f"**สิทธิ์สร้าง**\n{'✅ มีสิทธิ์สร้าง Familia' if can_create else '❌ ไม่มีสิทธิ์ (role ไม่ตรง)'}\n\n"
                f"**Passive income**\n`{cfg['passive_amount']:,}` ทุก `{cfg['passive_interval_min']}` นาที — โหมด `{cfg['passive_mode']}`\n\n"
                f"**คำเชิญที่ค้าง**\n`{len(invites)}` รายการ"
            ),
            color=0xc0392b,
        )
        await interaction.response.send_message(embed=embed, view=FamiliaEntryView(uid), ephemeral=eph)


@bot.tree.command(name="familiaแอดมิน", description="[Admin] จัดการ Familia + role + passive income", guild=_ORION_GUILD_OBJ)
async def cmd_familia_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    cfg = load_familia_cfg()
    fams = load_familias()
    roles_text = ", ".join(f"<@&{rid}>" for rid in cfg.get("allowed_role_ids", [])) or "_(ว่าง — admin เท่านั้น)_"
    embed = discord.Embed(
        title="⚜️  Familia — Admin Panel",
        description=(
            f"**Familia ในระบบ:** {len(fams)}\n"
            f"**Role ที่สร้างได้:** {roles_text}\n"
            f"**Passive:** {cfg['passive_amount']}/{cfg['passive_interval_min']}min · โหมด **{cfg['passive_mode']}**\n"
            f"**มินิเกมหาเงิน:** {len(cfg.get('minigame_keys',[]))} อัน · ครั้งละ {cfg['minigame_amount']}\n"
            f"**Max สมาชิก:** {cfg['max_members']}\n\n"
            "**Row 0** — ⚙️ ตั้งค่า · 🛡️ ตั้ง Role · 🎮 ตั้งมินิเกม\n"
            "**Row 1** — 📚 ดู Familia ทั้งหมด"
        ),
        color=0xc0392b,
    )
    await interaction.response.send_message(embed=embed, view=FamiliaAdminView(), ephemeral=True)


# Passive loop จะ start ใน on_ready ของ orion_bot — เพราะ start() ต้องการ event loop
# orion_bot.py จะเรียก orion_familia.familia_passive_loop.start() เอง
