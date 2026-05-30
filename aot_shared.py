"""Shared utilities — i18n, data helpers, UI, constants."""
import os, json, re, shutil
from pathlib import Path

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

RANK_EMBLEMS = {
    "Cadet":        "https://cdn.discordapp.com/attachments/1510115596992249886/1510115638541160448/IMG_2951.png",
    "Military":     "https://cdn.discordapp.com/attachments/1510115596992249886/1510115645906227240/IMG_2953.png",
    "Stationary":   "https://cdn.discordapp.com/attachments/1510115596992249886/1510115652784885831/IMG_2954.png",
    "Survey Corps": "https://cdn.discordapp.com/attachments/1510115596992249886/1510115664755425400/IMG_2955.png",
}

DEFAULT_CONFIG = {
    "language": "th",
    "roles": {"faction": {}, "rank": {}, "shifter": {}, "bloodline": {}},
    "factions": ["Survey Corps", "Military Police", "Garrison", "Stationary Guard", "Merchants", "Civilian"],
    "ranks": ["Cadet", "Soldier", "Section Commander", "Commander", "General"],
    "shifters": ["Attack Titan", "Armored Titan", "Colossal Titan", "Female Titan", "Beast Titan",
                 "Jaw Titan", "Cart Titan", "War Hammer Titan", "Founding Titan"],
    "bloodlines_common": ["Human", "Mixed Blood"],
    "bloodlines_special": ["Ackerman", "Royal Blood"],
    "special_access": {},
    "shifter_access": [],
    "titan_time_days": 4745,
    "titan_announcement_channel": None,
    "pending_moveset_requests": {},
    "stamina_regen_per_minute": 1,
}

# ── i18n ─────────────────────────────────────────────────────────────────────

LANG = {
    "th": {
        "profile_title": "โปรไฟล์ตัวละคร",
        "not_registered": "คุณยังไม่ได้ลงทะเบียนตัวละคร",
        "register_btn": "ลงทะเบียนตัวละคร",
        "profile_btn": "โปรไฟล์",
        "inventory_btn": "กระเป๋า",
        "edit_btn": "แก้ไขโปรไฟล์",
        "transform_btn": "⚔️ แปลงร่าง",
        "register_step2": "ลงทะเบียน — ขั้นตอนที่ 2\nเลือกรายละเอียดตัวละคร:",
        "confirm_btn": "ยืนยัน",
        "back_btn": "◀ กลับ",
        "done_btn": "เสร็จสิ้น",
        "name_field": "ชื่อตัวละคร",
        "age_field": "อายุ",
        "gender_field": "เพศ",
        "appearance_field": "รูปลักษณ์",
        "image_field": "รูปโปรไฟล์ (URL หรืออีโมจิ ไม่บังคับ)",
        "name_label": "ชื่อ",
        "age_label": "อายุ",
        "gender_label": "เพศ",
        "bloodline_label": "สายเลือด",
        "shifter_label": "ผู้แปลงร่าง",
        "faction_label": "สังกัด",
        "rank_label": "ยศ",
        "appearance_label": "รูปลักษณ์",
        "time_left_label": "เวลาที่เหลือ",
        "stamina_label": "พลังงาน",
        "registered_msg": "✅ **{name}** ลงทะเบียนตัวละคร **{char}** แล้ว!",
        "updated_msg": "✅ **{name}** อัปเดตตัวละคร **{char}** แล้ว!",
        "dm_profile": "นี่คือข้อมูลตัวละครของคุณ:\n\n{profile}",
        "select_faction": "เลือกสังกัด",
        "select_rank": "เลือกยศ",
        "select_bloodline": "เลือกสายเลือด",
        "select_shifter": "เลือกพลังไททัน",
        "no_options": "ไม่มีตัวเลือก",
        "not_your_profile": "นี่ไม่ใช่โปรไฟล์ของคุณ",
        "admin_title": "แผงควบคุมแอดมิน",
        "admin_desc": "จัดการบทบาท สังกัด และสายเลือด",
        "faction_roles_btn": "บทบาทสังกัด",
        "rank_roles_btn": "บทบาทยศ",
        "shifter_roles_btn": "บทบาทผู้แปลงร่าง",
        "bloodline_roles_btn": "บทบาทสายเลือด",
        "manage_factions_btn": "จัดการสังกัด",
        "manage_ranks_btn": "จัดการยศ",
        "manage_shifters_btn": "จัดการไททัน",
        "manage_bloodlines_btn": "จัดการสายเลือด",
        "grant_bloodline_btn": "ให้สิทธิ์สายเลือดพิเศษ",
        "grant_shifter_btn": "ให้สิทธิ์ผู้แปลงร่าง",
        "shifter_tracker_btn": "ติดตามผู้แปลงร่าง",
        "language_btn": "🌐 ตั้งค่าภาษา",
        "item_admin_title": "แผงจัดการไอเทม",
        "inventory_empty": "กระเป๋าว่างเปล่า",
        "titan_died": "⚰️ **{name}** สิ้นชีพแล้ว — พลัง **{titan}** ส่งต่อให้ **{new_owner}**",
        "got_titan_dm": "⚡ คุณได้รับพลังไททัน **{titan}** แล้ว!\n\nใช้ `/shifter` เพื่อดูและจัดการพลังของคุณ",
        "admin_got_titan": "📢 **{new_owner}** ได้รับพลัง **{titan}** ต่อจาก **{old_owner}**",
        "no_permission": "❌ คุณไม่มีสิทธิ์",
        "admin_only": "❌ ต้องเป็นแอดมิน",
        "select_value_first": "กรุณาเลือกค่าก่อน",
        "panel_closed": "ปิดแผงควบคุมแล้ว",
        "abilities_title": "ทักษะไททัน",
        "transform_public": "⚡ **{name}** แปลงร่างเป็น **{titan}**!",
        "transform_hidden": "⚡ มีไททันปรากฏตัวขึ้น!",
        "detransform_public": "**{name}** กลับสู่รูปร่างมนุษย์",
        "stamina_low": "⚠️ พลังงานต่ำ! คุณเหนื่อยมากและกำลังจะออกจากรูปร่างไททัน",
        "stamina_empty": "💀 พลังงานหมด! คุณถูกบังคับออกจากรูปร่างไททัน",
        "admin_stamina_warn": "⚠️ **{name}** มีพลังงานต่ำมาก ({stamina}/{max}) ขณะอยู่ในรูปร่างไททัน",
        "cooldown_remaining": "⏳ สกิลนี้ยังคูลดาวน์อยู่ อีก **{mins}** นาที",
        "ability_used": "✨ **{name}** ใช้ **{ability}**!",
        "moveset_pending": "📝 ส่งคำขอแก้ไขให้แอดมินอนุมัติแล้ว",
        "moveset_approved": "✅ คำขอแก้ไขมูฟเซต **{ability}** ได้รับการอนุมัติ",
        "moveset_declined": "❌ คำขอแก้ไขมูฟเซต **{ability}** ถูกปฏิเสธ",
        "approve_btn": "✅ อนุมัติ",
        "decline_btn": "❌ ปฏิเสธ",
        "hide_username_btn": "🎭 ซ่อนชื่อ",
        "show_username_btn": "👤 แสดงชื่อ",
        "use_ability_btn": "ใช้ทักษะ",
        "edit_moveset_btn": "แก้ไขมูฟเซต",
        "detransform_btn": "🔄 กลับสู่มนุษย์",
        "add_ability_btn": "เพิ่มทักษะ",
        "edit_ability_btn": "แก้ไขทักษะ",
        "delete_ability_btn": "ลบทักษะ",
        "set_shifter_time_btn": "ตั้งเวลาผู้แปลงร่าง",
        "no_titan_power": "คุณไม่มีพลังไททัน",
        "language_th": "🇹🇭 ภาษาไทย",
        "language_en": "🇬🇧 English",
        "language_set": "✅ ตั้งภาษาเป็น {lang} แล้ว",
        "balance_label": "เหรียญ",
        "got_bloodline_dm": "✨ คุณได้รับสิทธิ์สายเลือด **{bloodline}** แล้ว! ใช้ `/profile` เพื่ออัปเดต",
        "item_used_msg": "✅ คุณใช้ **{item}** แล้ว",
        "item_given_msg": "🎁 **{sender}** ส่ง **{item}** ให้คุณ!",
        "item_sold_msg": "💰 คุณขาย **{item}** ได้ **{price}** เหรียญ ยอดรวม: **{balance}** เหรียญ",
    },
    "en": {
        "profile_title": "Character Profile",
        "not_registered": "You haven't registered a character yet.",
        "register_btn": "Register Character",
        "profile_btn": "Profile",
        "inventory_btn": "Inventory",
        "edit_btn": "Edit Profile",
        "transform_btn": "⚔️ Transform",
        "register_step2": "Register — Step 2\nChoose your character details:",
        "confirm_btn": "Confirm",
        "back_btn": "◀ Back",
        "done_btn": "Done",
        "name_field": "Character Name",
        "age_field": "Age",
        "gender_field": "Gender",
        "appearance_field": "Appearance",
        "image_field": "Profile Image (URL or emoji, optional)",
        "name_label": "Name",
        "age_label": "Age",
        "gender_label": "Gender",
        "bloodline_label": "Bloodline",
        "shifter_label": "Shifter",
        "faction_label": "Faction",
        "rank_label": "Rank",
        "appearance_label": "Appearance",
        "time_left_label": "Time Left",
        "stamina_label": "Stamina",
        "registered_msg": "✅ **{name}** registered character **{char}**!",
        "updated_msg": "✅ **{name}** updated character **{char}**!",
        "dm_profile": "Here is your character profile:\n\n{profile}",
        "select_faction": "Choose Faction",
        "select_rank": "Choose Rank",
        "select_bloodline": "Choose Bloodline",
        "select_shifter": "Choose Titan Power",
        "no_options": "No options available",
        "not_your_profile": "This isn't your profile.",
        "admin_title": "Admin Panel",
        "admin_desc": "Manage roles, factions, and bloodlines.",
        "faction_roles_btn": "Faction Roles",
        "rank_roles_btn": "Rank Roles",
        "shifter_roles_btn": "Shifter Roles",
        "bloodline_roles_btn": "Bloodline Roles",
        "manage_factions_btn": "Manage Factions",
        "manage_ranks_btn": "Manage Ranks",
        "manage_shifters_btn": "Manage Titans",
        "manage_bloodlines_btn": "Manage Bloodlines",
        "grant_bloodline_btn": "Grant Special Bloodline",
        "grant_shifter_btn": "Grant Shifter Access",
        "shifter_tracker_btn": "Shifter Tracker",
        "language_btn": "🌐 Language",
        "item_admin_title": "Item Admin Panel",
        "inventory_empty": "Empty",
        "titan_died": "⚰️ **{name}** has perished — **{titan}** passed to **{new_owner}**",
        "got_titan_dm": "⚡ You received the **{titan}** power!\n\nUse `/shifter` to manage it.",
        "admin_got_titan": "📢 **{new_owner}** received **{titan}** from **{old_owner}**",
        "no_permission": "❌ You don't have permission.",
        "admin_only": "❌ Administrator only.",
        "select_value_first": "Please select a value first.",
        "panel_closed": "Panel closed.",
        "abilities_title": "Titan Abilities",
        "transform_public": "⚡ **{name}** transforms into the **{titan}**!",
        "transform_hidden": "⚡ A massive Titan appears!",
        "detransform_public": "**{name}** returns to human form.",
        "stamina_low": "⚠️ Low stamina! You are exhausted and about to de-transform.",
        "stamina_empty": "💀 Stamina depleted! You are forced out of Titan form.",
        "admin_stamina_warn": "⚠️ **{name}** has critically low stamina ({stamina}/{max}) while transformed.",
        "cooldown_remaining": "⏳ Ability on cooldown — **{mins}** min remaining.",
        "ability_used": "✨ **{name}** uses **{ability}**!",
        "moveset_pending": "📝 Edit request sent to admins for approval.",
        "moveset_approved": "✅ Moveset edit **{ability}** was approved.",
        "moveset_declined": "❌ Moveset edit **{ability}** was declined.",
        "approve_btn": "✅ Approve",
        "decline_btn": "❌ Decline",
        "hide_username_btn": "🎭 Hide Name",
        "show_username_btn": "👤 Show Name",
        "use_ability_btn": "Use Ability",
        "edit_moveset_btn": "Edit Moveset",
        "detransform_btn": "🔄 De-Transform",
        "add_ability_btn": "Add Ability",
        "edit_ability_btn": "Edit Ability",
        "delete_ability_btn": "Delete Ability",
        "set_shifter_time_btn": "Set Shifter Time",
        "no_titan_power": "You have no Titan power.",
        "language_th": "🇹🇭 Thai",
        "language_en": "🇬🇧 English",
        "language_set": "✅ Language set to {lang}.",
        "balance_label": "Coins",
        "got_bloodline_dm": "✨ You've been granted **{bloodline}** bloodline access! Use `/profile` to update.",
        "item_used_msg": "✅ You used **{item}**.",
        "item_given_msg": "🎁 **{sender}** sent you **{item}**!",
        "item_sold_msg": "💰 You sold **{item}** for **{price}** coins. Balance: **{balance}** coins.",
    },
}


def t(guild_id: int, key: str, **kwargs) -> str:
    cfg = load_config(guild_id)
    lang = cfg.get("language", "th")
    text = LANG.get(lang, LANG["th"]).get(key) or LANG["en"].get(key, key)
    return text.format(**kwargs) if kwargs else text


async def cv2_dm(user, text: str) -> None:
    try:
        import discord as _d
        v = _d.ui.LayoutView(timeout=None)
        v.add_item(_d.ui.Container(_d.ui.TextDisplay(text)))
        dm = await user.create_dm()
        await dm.send(view=v)
    except Exception:
        pass


# ── Data helpers ──────────────────────────────────────────────────────────────

def _load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default() if callable(default) else default


def _save_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    shutil.move(str(tmp), str(path))


def load_players(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"players_{guild_id}.json", dict)

def save_players(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"players_{guild_id}.json", data)

def load_config(guild_id: int) -> dict:
    raw = _load_json(DATA_DIR / f"config_{guild_id}.json", dict)
    merged = {**DEFAULT_CONFIG, **raw}
    for rtype in ("faction", "rank", "shifter", "bloodline"):
        merged["roles"].setdefault(rtype, {})
    return merged

def save_config(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"config_{guild_id}.json", data)

def load_items(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"items_{guild_id}.json",
                      lambda: {"categories": {}, "category_order": [], "items": {}})

def save_items(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"items_{guild_id}.json", data)


# ── Utilities ─────────────────────────────────────────────────────────────────

def slugify(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s_]", "", name)
    return re.sub(r"\s+", "_", name)

def is_url(text: str) -> bool:
    return text.strip().startswith(("http://", "https://"))

def select_options_from_list(items: list, current: str = None):
    import discord
    if not items:
        return [discord.SelectOption(label="—", value="__none__")]
    return [discord.SelectOption(label=str(s)[:100], value=str(s), default=(str(s) == current))
            for s in items[:25]]

def get_available_bloodlines(guild_id: int, user_id: int) -> list:
    cfg = load_config(guild_id)
    bl = list(cfg.get("bloodlines_common", []))
    granted = cfg.get("special_access", {}).get(str(user_id), [])
    bl += [b for b in cfg.get("bloodlines_special", []) if b in granted]
    return bl

def has_shifter_access(guild_id: int, user_id: int) -> bool:
    cfg = load_config(guild_id)
    return str(user_id) in cfg.get("shifter_access", [])




# ── Role helpers ──────────────────────────────────────────────────────────────

import discord as _discord

async def assign_roles(member: _discord.Member, player: dict, cfg: dict):
    roles_cfg = cfg.get("roles", {})
    to_add = []
    for field in ("faction", "rank", "shifter", "bloodline"):
        val = player.get(field)
        if not val or val in ("None", "__none__"): continue
        rid = roles_cfg.get(field, {}).get(val)
        if rid:
            r = member.guild.get_role(int(rid))
            if r: to_add.append(r)
    if to_add:
        try: await member.add_roles(*to_add, reason="AoT profile")
        except _discord.Forbidden: pass

async def remove_old_roles(member: _discord.Member, old: dict, cfg: dict):
    roles_cfg = cfg.get("roles", {})
    to_remove = []
    for field in ("faction", "rank", "shifter", "bloodline"):
        val = old.get(field)
        if not val or val in ("None", "__none__"): continue
        rid = roles_cfg.get(field, {}).get(val)
        if rid:
            r = member.guild.get_role(int(rid))
            if r and r in member.roles: to_remove.append(r)
    if to_remove:
        try: await member.remove_roles(*to_remove, reason="AoT profile update")
        except _discord.Forbidden: pass


# ── Profile text ──────────────────────────────────────────────────────────────

def format_profile_text(player: dict, display_name: str, guild_id: int) -> str:
    rank = player.get("rank", "?")
    balance = player.get("balance", 0)

    lines = [
        f"**{t(guild_id,'name_label')}** — {player.get('name','?')}",
        f"**{t(guild_id,'age_label')}** — {player.get('age','?')}",
        f"**{t(guild_id,'gender_label')}** — {player.get('gender','?')}",
        f"**{t(guild_id,'bloodline_label')}** — {player.get('bloodline','?')}",
        f"**{t(guild_id,'faction_label')}** — {player.get('faction','?')}",
        f"**{t(guild_id,'rank_label')}** — {rank}",
    ]
    if balance > 0:
        lines.append(f"**{t(guild_id,'balance_label')}** — {balance}")
    lines += [
        "",
        f"**{t(guild_id,'appearance_label')}**",
        f"*{player.get('appearance','?')}*",
    ]

    return f"**📋 {t(guild_id,'profile_title')} — {display_name}**\n\n" + "\n".join(lines)


def format_inventory_text(player: dict, items_data: dict, guild_id: int) -> str:
    inventory = player.get("inventory", {})
    categories = items_data.get("categories", {})
    cat_order  = items_data.get("category_order", [])
    all_items  = items_data.get("items", {})

    header = f"**🎒 {t(guild_id,'inventory_btn')}**"
    if not inventory:
        return header + "\n\n" + t(guild_id, "inventory_empty")

    grouped: dict = {}
    uncategorized = []
    for iid, qty in inventory.items():
        if qty <= 0: continue
        item = all_items.get(iid)
        if not item: continue
        cat_id = item.get("category", "")
        if cat_id in categories:
            grouped.setdefault(cat_id, []).append((item, qty))
        else:
            uncategorized.append((item, qty))

    lines = []
    for cat_id in [c for c in cat_order if c in grouped]:
        cat = categories[cat_id]
        lines.append(f"**{cat.get('emoji','📦')} {cat.get('name', cat_id)}**")
        for item, qty in grouped[cat_id]:
            lines.append(f"  {item.get('emoji','📦')} {item.get('name','?')} × {qty}")
        lines.append("")
    if uncategorized:
        lines.append("**📦 Other**")
        for item, qty in uncategorized:
            lines.append(f"  {item.get('emoji','📦')} {item.get('name','?')} × {qty}")

    return header + "\n\n" + ("\n".join(lines) if lines else t(guild_id, "inventory_empty"))
