# ============================================================
# ORION — Blacksmith/Creation System (separate module)
# ============================================================
# บทบาท Blacksmith/Creation — สร้าง Artifact Skill และ Item
# ผ่านการตรวจสอบโดย Admin ก่อนอนุมัติ
# ============================================================

import re
import sys
import time
import uuid as _uuid
import discord

# ── ดึง dependencies จาก orion_bot ────────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_creation ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                   = _orion_bot_mod.bot
ORION_GUILD_ID        = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ      = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR        = _orion_bot_mod.ORION_DATA_DIR
load_json             = _orion_bot_mod.load_json
save_json             = _orion_bot_mod.save_json
ensure_orion_player   = _orion_bot_mod.ensure_orion_player
load_orion_players    = _orion_bot_mod.load_orion_players
save_orion_players    = _orion_bot_mod.save_orion_players
load_skill_cats       = _orion_bot_mod.load_skill_cats

# ── ดึง dependencies จาก orion_items ──────────────────────────
import orion_items
load_items_catalog  = orion_items.load_items_catalog
save_items_catalog  = orion_items.save_items_catalog
add_player_item     = orion_items.add_player_item


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


def _safe_emoji(s, default="⚙️"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


# ============================================================
# DATA FILES
# ============================================================

CREATION_CONFIG_FILE  = f"{ORION_DATA_DIR}/creation_config.json"
CREATION_PENDING_FILE = f"{ORION_DATA_DIR}/creation_pending.json"

DEFAULT_CONFIG = {
    "creation_role_ids": [],
    "review_channel_id": None,
}


def load_creation_cfg() -> dict:
    cfg = load_json(CREATION_CONFIG_FILE, None)
    if not cfg:
        cfg = dict(DEFAULT_CONFIG)
        save_creation_cfg(cfg)
    return cfg


def save_creation_cfg(cfg: dict):
    save_json(CREATION_CONFIG_FILE, cfg)


def load_pending() -> list:
    return load_json(CREATION_PENDING_FILE, [])


def save_pending(lst: list):
    save_json(CREATION_PENDING_FILE, lst)


# ============================================================
# HELPERS
# ============================================================

def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w฀-๿]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or f"creation_{int(time.time())}"


def _new_uid() -> str:
    return _uuid.uuid4().hex[:8]


def _has_creation_role(member: discord.Member, role_ids: list) -> bool:
    if not role_ids:
        return False
    member_role_ids = {r.id for r in member.roles}
    return bool(member_role_ids & set(role_ids))


def _pending_by_id(pid: str):
    return next((p for p in load_pending() if p.get("id") == pid), None)


def _update_pending_status(pid: str, status: str):
    lst = load_pending()
    for p in lst:
        if p.get("id") == pid:
            p["status"] = status
            break
    save_pending(lst)


# ============================================================
# EMBEDS
# ============================================================

def _review_embed(entry: dict, status_line: str = "") -> discord.Embed:
    etype = entry.get("type", "?")
    data  = entry.get("data", {})
    uid   = entry.get("creator_uid", "?")
    pid   = entry.get("id", "?")

    if etype == "skill":
        title  = "🔨 คำขอสร้าง Artifact Skill"
        color  = 0xe67e22
        lines  = []
        lines.append(f"**ชื่อ:** {data.get('name','?')}")
        lines.append(f"**คำอธิบาย:**\n{data.get('description','—')}")
        if data.get("icon"):
            lines.append(f"**Icon:** {data['icon']}")
        if data.get("cooldown_desc"):
            lines.append(f"**Cooldown:** {data['cooldown_desc']}")
        if data.get("drawback"):
            lines.append(f"**Drawback:**\n{data['drawback']}")
        lines.append(f"**Rank:** {data.get('rank','—')}")
        description = "\n".join(lines)
    elif etype == "craft":
        title = "⚒️ คำขอ Craft"
        color = 0x9b59b6
        mats  = data.get("materials", [])
        mat_lines = [f"• {m['name']} × {m['qty']}" for m in mats] or ["—"]
        note  = data.get("note", "")
        lines = ["**วัสดุที่ใช้:**"] + mat_lines
        if note:
            lines.append(f"\n**โน้ต:**\n{note}")
        description = "\n".join(lines)
    else:
        title  = "🔨 คำขอสร้าง Item"
        color  = 0x3498db
        lines  = []
        lines.append(f"**ชื่อ:** {data.get('name','?')}")
        if data.get("emoji"):
            lines.append(f"**Emoji:** {data['emoji']}")
        lines.append(f"**คำอธิบาย:**\n{data.get('description','—')}")
        lines.append(f"**ประเภท:** {data.get('item_type','—')}")
        lines.append(f"**Rarity:** {data.get('rarity','—')}")
        description = "\n".join(lines)

    if status_line:
        description += f"\n\n{status_line}"

    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text=f"ผู้สร้าง: <@{uid}> | ID: {pid}")
    return embed


def _approve_dm_embed(entry: dict, admin_note: str = "") -> discord.Embed:
    etype = entry.get("type", "?")
    data  = entry.get("data", {})
    if etype == "skill":
        embed = discord.Embed(
            title="✅ Artifact Skill ของคุณได้รับการอนุมัติ!",
            description=(
                f"**ชื่อสกิล:** {data.get('name','?')}\n"
                f"**คำอธิบาย:** {data.get('description','—')[:300]}"
            ),
            color=0x2ecc71,
        )
    elif etype == "craft":
        mats = data.get("materials", [])
        mat_str = ", ".join(f"{m['name']} ×{m['qty']}" for m in mats) or "—"
        embed = discord.Embed(
            title="✅ คำขอ Craft ของคุณได้รับการอนุมัติ!",
            description=f"**วัสดุ:** {mat_str}",
            color=0x2ecc71,
        )
        if admin_note:
            embed.add_field(name="ข้อความจาก Admin", value=admin_note, inline=False)
    else:
        embed = discord.Embed(
            title="✅ Item ของคุณได้รับการอนุมัติ!",
            description=(
                f"**ชื่อ:** {data.get('name','?')}\n"
                f"**ประเภท:** {data.get('item_type','—')} · "
                f"**Rarity:** {data.get('rarity','—')}"
            ),
            color=0x2ecc71,
        )
    embed.set_footer(text="Orion · Creation System")
    return embed


def _decline_dm_embed(entry: dict, reason: str) -> discord.Embed:
    etype = entry.get("type", "?")
    data  = entry.get("data", {})
    if etype == "craft":
        mats = data.get("materials", [])
        name = ", ".join(m["name"] for m in mats[:3]) + ("…" if len(mats) > 3 else "")
        label = "Craft"
    else:
        name  = data.get("name", "?")
        label = "Artifact Skill" if etype == "skill" else "Item"
    embed = discord.Embed(
        title=f"❌ คำขอสร้าง {label} ถูกปฏิเสธ",
        description=(
            f"**วัสดุ/ชื่อ:** {name}\n"
            f"**เหตุผล:** {reason or '_(ไม่ระบุ)_'}"
        ),
        color=0xe74c3c,
    )
    embed.set_footer(text="Orion · Creation System")
    return embed


# ============================================================
# MODALS
# ============================================================

# Discord modals allow max 5 TextInput components.
# Spec has 6 fields (Name, Desc, Icon, Cooldown, Drawback, Rank).
# Icon and Cooldown are merged into one multi-line field (2 lines).

class CreateArtifactSkillModal(discord.ui.Modal, title="⚙️ สร้าง Artifact Skill"):
    f_name       = discord.ui.TextInput(label="ชื่อสกิล", max_length=80)
    f_desc       = discord.ui.TextInput(
        label="คำอธิบาย",
        style=discord.TextStyle.paragraph,
        max_length=1500,
    )
    f_icon_cd    = discord.ui.TextInput(
        label="Icon/Emoji · Cooldown (แยกบรรทัด, ไม่บังคับ)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=300,
        placeholder="บรรทัด 1: icon หรือ emoji\nบรรทัด 2: คำอธิบาย cooldown",
    )
    f_drawback   = discord.ui.TextInput(
        label="Drawback / ผลเสีย (ไม่บังคับ)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=400,
    )
    f_rank       = discord.ui.TextInput(
        label="Rank",
        max_length=10,
        placeholder="เช่น A, S, SSS",
        required=False,
    )

    def __init__(self, creator_uid: str):
        super().__init__()
        self.creator_uid = creator_uid

    async def on_submit(self, ix: discord.Interaction):
        raw_icon_cd = (self.f_icon_cd.value or "").strip()
        lines_ic    = [ln.strip() for ln in raw_icon_cd.splitlines() if ln.strip()]
        icon        = lines_ic[0] if len(lines_ic) >= 1 else ""
        cooldown_desc = lines_ic[1] if len(lines_ic) >= 2 else ""

        data = {
            "name":         self.f_name.value.strip(),
            "description":  self.f_desc.value.strip(),
            "icon":         icon,
            "cooldown_desc": cooldown_desc,
            "drawback":     (self.f_drawback.value or "").strip(),
            "rank":         (self.f_rank.value or "").strip(),
        }
        entry = {
            "id":          _new_uid(),
            "type":        "skill",
            "creator_uid": self.creator_uid,
            "data":        data,
            "status":      "pending",
            "created_at":  time.time(),
        }
        lst = load_pending()
        lst.append(entry)
        save_pending(lst)

        await _send_to_review(ix, entry)


class CreateItemModal(discord.ui.Modal, title="📦 สร้าง Item"):
    f_name      = discord.ui.TextInput(label="ชื่อไอเทม", max_length=80)
    f_emoji     = discord.ui.TextInput(
        label="Emoji (ไม่บังคับ)",
        required=False,
        max_length=20,
    )
    f_desc      = discord.ui.TextInput(
        label="คำอธิบาย",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )
    f_item_type = discord.ui.TextInput(
        label="ประเภท (consumable/equipment/material)",
        max_length=50,
        placeholder="consumable / equipment / material",
        required=False,
    )
    f_rarity    = discord.ui.TextInput(
        label="Rarity (common/uncommon/rare/epic/legendary)",
        max_length=20,
        placeholder="common / uncommon / rare / epic / legendary",
        required=False,
    )

    def __init__(self, creator_uid: str):
        super().__init__()
        self.creator_uid = creator_uid

    async def on_submit(self, ix: discord.Interaction):
        data = {
            "name":      self.f_name.value.strip(),
            "emoji":     (self.f_emoji.value or "").strip(),
            "description": self.f_desc.value.strip(),
            "item_type": (self.f_item_type.value or "material").strip().lower(),
            "rarity":    (self.f_rarity.value or "common").strip().lower(),
        }
        entry = {
            "id":          _new_uid(),
            "type":        "item",
            "creator_uid": self.creator_uid,
            "data":        data,
            "status":      "pending",
            "created_at":  time.time(),
        }
        lst = load_pending()
        lst.append(entry)
        save_pending(lst)

        await _send_to_review(ix, entry)


class DeclineReasonModal(discord.ui.Modal, title="❌ เหตุผลที่ปฏิเสธ"):
    f_reason = discord.ui.TextInput(
        label="เหตุผล (ไม่บังคับ)",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, entry: dict, review_message: discord.Message):
        super().__init__()
        self.entry          = entry
        self.review_message = review_message

    async def on_submit(self, ix: discord.Interaction):
        reason = (self.f_reason.value or "").strip()
        pid    = self.entry.get("id")

        _update_pending_status(pid, "declined")

        admin_tag = ix.user.mention
        status_line = f"❌ ปฏิเสธ by {admin_tag}" + (f" — {reason}" if reason else "")
        new_embed = _review_embed(self.entry, status_line=status_line)
        try:
            await self.review_message.edit(embed=new_embed, view=None)
        except Exception:
            pass

        # DM creator
        creator_uid = self.entry.get("creator_uid")
        if creator_uid:
            try:
                user = await bot.fetch_user(int(creator_uid))
                await user.send(embed=_decline_dm_embed(self.entry, reason))
            except Exception:
                pass

        await ix.response.send_message("❌ ปฏิเสธคำขอแล้ว", ephemeral=True)


# ============================================================
# VIEWS
# ============================================================

async def _send_to_review(ix: discord.Interaction, entry: dict):
    """ส่ง embed ไปยัง review channel และ confirm กับ creator"""
    cfg = load_creation_cfg()
    review_ch_id = cfg.get("review_channel_id")

    review_msg = None
    if review_ch_id:
        try:
            ch = ix.guild.get_channel(int(review_ch_id))
            if ch is None:
                ch = await bot.fetch_channel(int(review_ch_id))
            embed  = _review_embed(entry)
            review_view = CreationReviewView(entry, review_message_ref=[None])
            review_msg  = await ch.send(embed=embed, view=review_view)
            review_view.review_message_ref[0] = review_msg
        except Exception as e:
            print(f"[orion_creation] cannot send to review channel: {e}")

    await ix.response.send_message(
        "✅ ส่งขอสร้างแล้ว รอ Admin ตรวจสอบ",
        ephemeral=True,
    )


class CreationReviewView(discord.ui.View):
    """View สำหรับ Admin ในห้อง review"""

    def __init__(self, entry: dict, review_message_ref: list):
        super().__init__(timeout=None)
        self.entry              = entry
        # review_message_ref is a 1-element list so we can set it after send
        self.review_message_ref = review_message_ref

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.manage_guild:
            await ix.response.send_message(
                "❌ ต้องมีสิทธิ์ Manage Server เพื่อตรวจสอบคำขอ",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="✅ อนุมัติ", style=discord.ButtonStyle.success, row=0)
    async def btn_approve(self, ix: discord.Interaction, _btn: discord.ui.Button):
        if self.entry.get("type") == "craft":
            await ix.response.send_modal(_CraftApproveModal(self.entry, self.review_message_ref))
        else:
            await self._do_approve(ix)

    @discord.ui.button(label="❌ ปฏิเสธ", style=discord.ButtonStyle.danger, row=0)
    async def btn_decline(self, ix: discord.Interaction, _btn: discord.ui.Button):
        review_msg = self.review_message_ref[0]
        if review_msg is None:
            # fallback: try to get message from interaction
            review_msg = ix.message
        await ix.response.send_modal(DeclineReasonModal(self.entry, review_msg))

    async def _do_approve(self, ix: discord.Interaction):
        pid  = self.entry.get("id")
        etype = self.entry.get("type")
        data  = self.entry.get("data", {})
        creator_uid = self.entry.get("creator_uid")

        if etype == "item":
            # Build item entry for catalog
            cat   = load_items_catalog()
            base  = _slugify(data.get("name", "item"))
            slug  = base
            # ensure unique key
            counter = 1
            while slug in cat:
                slug = f"{base}_{counter}"
                counter += 1
            emoji = data.get("emoji", "") or "📦"
            cat[slug] = {
                "name":        data.get("name", "?"),
                "emoji":       emoji,
                "image_url":   "",
                "description": data.get("description", ""),
                "sell_price":  0,
                "type":        data.get("item_type", "material"),
                "rarity":      data.get("rarity", "common"),
                "created_by":  creator_uid,
            }
            save_items_catalog(cat)
            # Give item to creator
            if creator_uid:
                ensure_orion_player(creator_uid)
                add_player_item(creator_uid, slug, 1)

        elif etype == "skill":
            # Add artifact skill to creator's skills list
            if creator_uid:
                ensure_orion_player(creator_uid)
                players = load_orion_players()
                base = _slugify(data.get("name", "skill"))
                existing_ids = {
                    sk.get("id", "") for sk in players.get(creator_uid, {}).get("skills", [])
                }
                slug = base
                counter = 1
                while slug in existing_ids:
                    slug = f"{base}_{counter}"
                    counter += 1
                skill_entry = {
                    "id":           slug,
                    "name":         data.get("name", "?"),
                    "category":     "artifact",
                    "description":  data.get("description", ""),
                    "icon":         data.get("icon", ""),
                    "cooldown_desc": data.get("cooldown_desc", ""),
                    "drawback":     data.get("drawback", ""),
                    "rank":         data.get("rank", ""),
                    "transferable": True,
                }
                players[creator_uid].setdefault("skills", []).append(skill_entry)
                save_orion_players(players)

        _update_pending_status(pid, "approved")

        admin_tag   = ix.user.mention
        status_line = f"✅ อนุมัติแล้ว by {admin_tag}"
        new_embed   = _review_embed(self.entry, status_line=status_line)

        review_msg = self.review_message_ref[0]
        if review_msg is None:
            review_msg = ix.message
        try:
            await review_msg.edit(embed=new_embed, view=None)
        except Exception:
            pass

        # DM creator
        if creator_uid:
            try:
                user = await bot.fetch_user(int(creator_uid))
                await user.send(embed=_approve_dm_embed(self.entry))
            except Exception:
                pass

        await ix.response.send_message("✅ อนุมัติคำขอแล้ว", ephemeral=True)


# ── Craft Approval Modal ──────────────────────────────────────

class _CraftApproveModal(discord.ui.Modal, title="อนุมัติ Craft"):
    f_note = discord.ui.TextInput(
        label="ข้อความถึงผู้เล่น (ไม่บังคับ)",
        style=discord.TextStyle.paragraph,
        max_length=300,
        required=False,
        placeholder="เช่น: ได้รับ Iron Sword แล้ว / จะส่ง DM ทีหลัง…",
    )

    def __init__(self, entry: dict, review_message_ref: list):
        super().__init__()
        self.entry = entry
        self.review_message_ref = review_message_ref

    async def on_submit(self, ix: discord.Interaction):
        pid = self.entry.get("id")
        creator_uid = self.entry.get("creator_uid")
        admin_note = self.f_note.value.strip()

        _update_pending_status(pid, "approved")

        status_line = f"✅ อนุมัติแล้ว by {ix.user.mention}"
        if admin_note:
            status_line += f"\n**หมายเหตุ:** {admin_note}"
        new_embed = _review_embed(self.entry, status_line=status_line)

        review_msg = self.review_message_ref[0]
        if review_msg is None:
            review_msg = ix.message
        try:
            await review_msg.edit(embed=new_embed, view=None)
        except Exception:
            pass

        if creator_uid:
            try:
                user = await bot.fetch_user(int(creator_uid))
                await user.send(embed=_approve_dm_embed(self.entry, admin_note))
            except Exception:
                pass

        await ix.response.send_message("✅ อนุมัติคำขอ Craft แล้ว", ephemeral=True)


# ── Craft Draft View ──────────────────────────────────────────

class CraftDraftView(discord.ui.View):
    """Draft view for crafting — player selects raw materials from inventory."""

    def __init__(self, uid: str, inv_materials: list, draft: dict = None):
        super().__init__(timeout=300)
        self.uid = uid
        self.inv_materials = inv_materials  # [{"item_id", "name", "qty", "description"}]
        self.draft = draft or {}            # {item_id: {"name", "qty"}}
        self._build()

    def _build(self):
        self.clear_items()
        if self.inv_materials:
            opts = [
                discord.SelectOption(
                    label=f"{m['name']} (มี {m['qty']})",
                    value=m["item_id"],
                    description=(m.get("description") or "")[:100],
                )
                for m in self.inv_materials[:25]
            ]
            sel = discord.ui.Select(placeholder="เลือกวัสดุ…", options=opts, row=0)
            sel.callback = self._on_select
            self.add_item(sel)

        clear_btn = discord.ui.Button(label="ล้างแบบร่าง", style=discord.ButtonStyle.secondary, row=1)
        clear_btn.callback = self._clear
        self.add_item(clear_btn)

        if self.draft:
            submit_btn = discord.ui.Button(label="✅ ส่งคำขอ Craft", style=discord.ButtonStyle.success, row=1)
            submit_btn.callback = self._submit
            self.add_item(submit_btn)

        cancel_btn = discord.ui.Button(label="ยกเลิก", style=discord.ButtonStyle.danger, row=1)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

    def _embed(self) -> discord.Embed:
        embed = discord.Embed(title="⚒️ Crafting — แบบร่าง", color=0x9b59b6)
        if self.draft:
            lines = [f"• **{v['name']}** × {v['qty']}" for v in self.draft.values()]
            embed.description = "\n".join(lines)
            embed.set_footer(text=f"วัสดุ {len(self.draft)}/10 ชนิด")
        else:
            embed.description = "*ยังไม่มีวัสดุ — เลือกจาก dropdown ด้านล่าง*"
        return embed

    async def _on_select(self, ix: discord.Interaction):
        item_id = ix.data["values"][0]
        item = next((m for m in self.inv_materials if m["item_id"] == item_id), None)
        if not item:
            await ix.response.defer(); return
        if item_id not in self.draft and len(self.draft) >= 10:
            await ix.response.send_message("สามารถเพิ่มได้สูงสุด 10 ชนิด", ephemeral=True); return
        current_qty = self.draft.get(item_id, {}).get("qty", 1)
        await ix.response.send_modal(
            _CraftQtyModal(self, item_id, item["name"], item["qty"], current_qty)
        )

    async def _clear(self, ix: discord.Interaction):
        self.draft.clear(); self._build()
        await ix.response.edit_message(embed=self._embed(), view=self)

    async def _submit(self, ix: discord.Interaction):
        await ix.response.send_modal(_CraftNoteModal(self))

    async def _cancel(self, ix: discord.Interaction):
        embed = discord.Embed(description="*ยกเลิกการ Craft แล้ว*", color=0x2f3136)
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)


class _CraftQtyModal(discord.ui.Modal, title="ใส่จำนวนวัสดุ"):
    f_qty = discord.ui.TextInput(label="จำนวน", max_length=5, placeholder="1")

    def __init__(self, parent: CraftDraftView, item_id: str, name: str, max_qty: int, current_qty: int):
        super().__init__()
        self.parent = parent
        self.item_id = item_id
        self.name = name
        self.max_qty = max_qty
        self.f_qty.label = f"จำนวน (มีอยู่ {max_qty} ชิ้น)"
        self.f_qty.default = str(current_qty)

    async def on_submit(self, ix: discord.Interaction):
        try:
            qty = int(self.f_qty.value.strip())
        except ValueError:
            await ix.response.send_message("จำนวนไม่ถูกต้อง", ephemeral=True); return
        if qty <= 0:
            self.parent.draft.pop(self.item_id, None)
        elif qty > self.max_qty:
            await ix.response.send_message(f"มีแค่ {self.max_qty} ชิ้น", ephemeral=True); return
        else:
            self.parent.draft[self.item_id] = {"name": self.name, "qty": qty}
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)


class _CraftNoteModal(discord.ui.Modal, title="โน้ตสำหรับ Admin"):
    f_note = discord.ui.TextInput(
        label="สิ่งที่ต้องการสร้าง / รายละเอียด",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
        placeholder="อธิบายว่าต้องการสร้างอะไรจากวัสดุเหล่านี้…",
    )

    def __init__(self, parent: CraftDraftView):
        super().__init__()
        self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        from orion_items import remove_player_item, player_qty
        uid   = self.parent.uid
        draft = self.parent.draft
        note  = self.f_note.value.strip()

        for item_id, info in draft.items():
            if player_qty(uid, item_id) < info["qty"]:
                await ix.response.send_message(
                    f"วัสดุ **{info['name']}** ไม่เพียงพอแล้ว", ephemeral=True
                ); return

        for item_id, info in draft.items():
            remove_player_item(uid, item_id, info["qty"])

        materials = [{"item_id": k, "name": v["name"], "qty": v["qty"]} for k, v in draft.items()]
        entry = {
            "id":          _new_uid(),
            "type":        "craft",
            "creator_uid": uid,
            "status":      "pending",
            "data":        {"materials": materials, "note": note},
        }
        lst = load_pending()
        lst.append(entry)
        save_pending(lst)

        cfg = load_creation_cfg()
        review_ch_id = cfg.get("review_channel_id")
        if review_ch_id and ix.guild:
            ch = ix.guild.get_channel(int(review_ch_id))
            if ch:
                ref = [None]
                msg = await ch.send(embed=_review_embed(entry), view=CreationReviewView(entry, ref))
                ref[0] = msg

        embed = discord.Embed(
            title="✅ ส่งคำขอ Craft แล้ว",
            description=(
                f"วัสดุ **{len(materials)}** ชนิดถูกนำออกจาก inventory แล้ว\n"
                "รอ Admin ตรวจสอบและอนุมัติ"
            ),
            color=0x2ecc71,
        )
        self.parent.clear_items()
        await ix.response.edit_message(embed=embed, view=None)


# ── Creation Type Select ──────────────────────────────────────

class CreationTypeView(discord.ui.View):
    """View ให้ผู้เล่นเลือกประเภทที่จะสร้าง"""

    def __init__(self, creator_uid: str):
        super().__init__(timeout=120)
        self.creator_uid = creator_uid

    @discord.ui.button(label="⚙️ Artifact Skill", style=discord.ButtonStyle.primary, row=0)
    async def btn_skill(self, ix: discord.Interaction, _btn: discord.ui.Button):
        await ix.response.send_modal(CreateArtifactSkillModal(self.creator_uid))

    @discord.ui.button(label="📦 Item", style=discord.ButtonStyle.secondary, row=0)
    async def btn_item(self, ix: discord.Interaction, _btn: discord.ui.Button):
        await ix.response.send_modal(CreateItemModal(self.creator_uid))

    @discord.ui.button(label="⚒️ Craft", style=discord.ButtonStyle.success, row=0)
    async def btn_craft(self, ix: discord.Interaction, _btn: discord.ui.Button):
        from orion_items import get_player_inv, load_items_catalog
        uid = self.creator_uid
        inv = get_player_inv(uid)
        cat = load_items_catalog()
        materials = []
        for entry in inv:
            item_id = entry.get("item_id", "")
            qty = int(entry.get("qty", 0))
            if qty <= 0: continue
            item = cat.get(item_id, {})
            if item.get("type", "").lower() == "material":
                materials.append({
                    "item_id": item_id,
                    "name": item.get("name", item_id),
                    "qty": qty,
                    "description": item.get("description", ""),
                })
        if not materials:
            await ix.response.send_message(
                "❌ ไม่มีวัสดุ (material) ใน inventory ของคุณ", ephemeral=True
            ); return
        view = CraftDraftView(uid, materials)
        await ix.response.edit_message(embed=view._embed(), view=view)


# ── Admin Views ───────────────────────────────────────────────

class CreationConfigModal(discord.ui.Modal, title="⚙️ ตั้งค่า Creation"):
    f_channel = discord.ui.TextInput(
        label="Review Channel ID",
        placeholder="เช่น 1234567890123456789",
        max_length=30,
        required=False,
    )

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_creation_cfg()
        raw = (self.f_channel.value or "").strip()
        if raw.isdigit():
            cfg["review_channel_id"] = int(raw)
            ch_text = f"<#{raw}>"
        elif raw == "":
            cfg["review_channel_id"] = None
            ch_text = "_(ล้างแล้ว)_"
        else:
            await ix.response.send_message("❌ Channel ID ไม่ถูกต้อง", ephemeral=True)
            return
        save_creation_cfg(cfg)
        await ix.response.send_message(
            f"✅ ตั้ง Review Channel เป็น {ch_text}",
            ephemeral=True,
        )


class CreationRoleSelect(discord.ui.RoleSelect):
    def __init__(self, current_ids: list):
        super().__init__(
            placeholder="เลือก Role ที่ใช้สร้างได้ (สูงสุด 5)...",
            min_values=0,
            max_values=5,
        )

    async def callback(self, ix: discord.Interaction):
        cfg = load_creation_cfg()
        cfg["creation_role_ids"] = [r.id for r in self.values]
        save_creation_cfg(cfg)
        names = ", ".join(r.mention for r in self.values) or "_(ว่าง — ไม่มีใครสร้างได้)_"
        await ix.response.send_message(f"✅ ตั้ง Role ที่สร้างได้: {names}", ephemeral=True)


class CreationAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        cfg = load_creation_cfg()
        self.add_item(CreationRoleSelect(cfg.get("creation_role_ids", [])))

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.manage_guild:
            await ix.response.send_message("❌ ต้องมีสิทธิ์ Manage Server", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚙️ ตั้งค่า", style=discord.ButtonStyle.primary, row=1)
    async def btn_config(self, ix: discord.Interaction, _btn: discord.ui.Button):
        await ix.response.send_modal(CreationConfigModal())

    @discord.ui.button(label="❌ ปิด", style=discord.ButtonStyle.secondary, row=1)
    async def btn_close(self, ix: discord.Interaction, _btn: discord.ui.Button):
        try:
            await ix.response.edit_message(content="✓", embed=None, view=None)
        except Exception:
            await ix.response.defer()


def _admin_panel_embed() -> discord.Embed:
    cfg = load_creation_cfg()
    role_ids = cfg.get("creation_role_ids", [])
    ch_id    = cfg.get("review_channel_id")

    roles_text = ", ".join(f"<@&{rid}>" for rid in role_ids) or "_(ว่าง)_"
    ch_text    = f"<#{ch_id}>" if ch_id else "_(ยังไม่ตั้ง)_"

    embed = discord.Embed(
        title="🔨  Creation — Admin Panel",
        description=(
            f"**Role ที่สร้างได้:** {roles_text}\n"
            f"**Review Channel:** {ch_text}\n\n"
            "**Row 0** — RoleSelect (เลือก role ที่ใช้สร้างได้)\n"
            "**Row 1** — ⚙️ ตั้งค่า (ตั้ง review channel) · ❌ ปิด"
        ),
        color=0xe67e22,
    )
    embed.set_footer(text="Orion · Creation Admin")
    return embed


# ============================================================
# SLASH COMMANDS
# ============================================================

@bot.tree.command(name="สร้าง", description="สร้าง Artifact Skill หรือ Item (ต้องมี Role ที่กำหนด)", guild=_ORION_GUILD_OBJ)
async def cmd_creation(ix: discord.Interaction):
    if not ix.guild or ix.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await ix.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True)
        return

    cfg      = load_creation_cfg()
    role_ids = cfg.get("creation_role_ids", [])

    if not _has_creation_role(ix.user, role_ids):
        await ix.response.send_message(
            "❌ คุณไม่มี Role ที่อนุญาตให้สร้างได้ — ติดต่อ Admin เพื่อขอสิทธิ์",
            ephemeral=True,
        )
        return

    uid = str(ix.user.id)
    embed = discord.Embed(
        title="🔨 ระบบสร้าง — Blacksmith",
        description=(
            "เลือกประเภทที่ต้องการสร้าง:\n\n"
            "⚙️ **Artifact Skill** — สกิล Artifact ที่ใช้ได้กับตัวละครของคุณ\n"
            "📦 **Item** — ไอเทมที่จะเพิ่มเข้า catalog และ inventory ของคุณ\n\n"
            "_คำขอจะถูกส่งให้ Admin ตรวจสอบก่อนอนุมัติ_"
        ),
        color=0xe67e22,
    )
    await ix.response.send_message(embed=embed, view=CreationTypeView(uid), ephemeral=True)


@bot.tree.command(name="สร้างแอดมิน", description="[Admin] จัดการระบบ Creation", guild=_ORION_GUILD_OBJ)
async def cmd_creation_admin(ix: discord.Interaction):
    if not ix.guild or ix.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await ix.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True)
        return
    if not ix.user.guild_permissions.manage_guild:
        await ix.response.send_message("❌ ต้องมีสิทธิ์ Manage Server", ephemeral=True)
        return
    await ix.response.send_message(embed=_admin_panel_embed(), view=CreationAdminView(), ephemeral=True)
