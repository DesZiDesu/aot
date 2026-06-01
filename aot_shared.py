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
    "faction_roles": [
        {"name": "Recruit",         "image": RANK_EMBLEMS.get("Cadet", ""),        "ranks": [{"name": "Cadet",             "visible": True}]},
        {"name": "Survey Corps",    "image": RANK_EMBLEMS.get("Survey Corps", ""), "ranks": [{"name": "Soldier",           "visible": True},
                                                                                              {"name": "Section Commander", "visible": False},
                                                                                              {"name": "Commander",         "visible": False},
                                                                                              {"name": "General",           "visible": False}]},
        {"name": "Military Police", "image": RANK_EMBLEMS.get("Military", ""),     "ranks": [{"name": "Cadet",             "visible": True},
                                                                                              {"name": "MP Soldier",        "visible": False},
                                                                                              {"name": "MP Officer",        "visible": False}]},
        {"name": "Garrison",        "image": RANK_EMBLEMS.get("Stationary", ""),   "ranks": [{"name": "Cadet",             "visible": True},
                                                                                              {"name": "Soldier",           "visible": False},
                                                                                              {"name": "Officer",           "visible": False}]},
        {"name": "Stationary Guard","image": "",                                   "ranks": [{"name": "Guard",             "visible": True},
                                                                                              {"name": "Commander",         "visible": False}]},
        {"name": "Merchants",       "image": "",                                   "ranks": [{"name": "Merchant",          "visible": True}]},
        {"name": "Civilian",        "image": "",                                   "ranks": [{"name": "Civilian",          "visible": True}]},
    ],
    "rank_access": {},
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
    "stamina_regen_interval_minutes": 5,
    "stamina_regen_amount": 5,
    "auto_deform_cooldown_minutes": 60,
    "transform_min_stamina": 30,
    "announcement_channels": [],
    "announcement_permitted_roles": [],
    "currency_name": "Coins",
    "currency_emoji": "",
    "currency_image": "",
    "logs_channel": None,
    "logs_categories": {},
    "mission_channels": [],
    "mission_log_channels": [],
    "inheritance_races": ["Eldian", "Mixed Blood Eldian"],
    "error_log_channel": None,
    "squad_max_members": 6,
    "squad_creator_ranks": ["Commander", "General"],
    "mindless_syringe_item": "",
    "mindless_fluid_item": "",
    "xp_enabled": True,
    "required_creation_role_id": None,
    "mindless_role_id": None,
    "bloodlines_immune_mindless": [],
    "bloodlines_immune_shifter": [],
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
        "config_title": "ตั้งค่า",
        "config_page": "หน้า {page}/{total}",
        "prev_btn": "◀ ก่อนหน้า",
        "next_btn": "ถัดไป ▶",
        "general_page": "🔧 ทั่วไป",
        "roles_page": "🎭 บทบาท",
        "lists_page": "📋 รายการ",
        "permissions_page": "🔑 สิทธิ์",
        "language_section": "🌐 ภาษา",
        "currency_section": "💰 สกุลเงิน",
        "ann_channels_section": "📢 ช่องทางประกาศ",
        "configure_btn": "ตั้งค่า",
        "currency_name_field": "ชื่อสกุลเงิน",
        "currency_emoji_field": "อิโมจิ (ไม่บังคับ)",
        "currency_img_field": "URL รูปภาพ (ไม่บังคับ)",
        "announcement_title": "📢 การประกาศ",
        "create_draft_btn": "สร้างร่างประกาศ",
        "no_drafts": "ยังไม่มีร่างประกาศ",
        "draft_name_field": "ชื่อประกาศ",
        "draft_created": "✅ สร้างร่างประกาศ **{name}** แล้ว",
        "edit_title_btn": "แก้ไขชื่อเรื่อง",
        "edit_content_btn": "แก้ไขเนื้อหา",
        "publish_btn": "🚀 เผยแพร่",
        "delete_draft_btn": "🗑️ ลบ",
        "ann_title_field": "ชื่อเรื่อง",
        "ann_content_field": "เนื้อหา",
        "ann_published": "📢 เผยแพร่แล้ว!",
        "no_ann_channels": "❌ ยังไม่ได้ตั้งค่าช่องทางประกาศ ใช้ /config หน้า 1 เพื่อตั้งค่า",
        "ann_no_permission": "❌ คุณไม่มีสิทธิ์ใช้คำสั่งนี้",
        "ann_permitted_roles_section": "🔑 สิทธิ์ใช้คำสั่งประกาศ",
        "shop_title": "🏪 ร้านค้า",
        "shop_setup_title": "ตั้งค่าร้านค้าใหม่",
        "shop_config_title": "จัดการร้านค้า",
        "no_shops": "ยังไม่มีร้านค้า",
        "shop_name_field": "ชื่อร้านค้า",
        "shop_owner_field": "เจ้าของร้าน",
        "shop_desc_field": "คำอธิบายร้านค้า",
        "style_channel": "ช่องข้อความ",
        "style_thread": "เธรด",
        "style_forum": "ฟอรัม",
        "shop_created": "✅ สร้างร้านค้า **{name}** แล้ว",
        "shop_img_field": "URL รูปภาพ (ไม่บังคับ)",
        "out_of_stock_label": "หมดสต็อก",
        "purchase_success": "✅ ซื้อ **{item}** สำเร็จ ราคา **{price}** คงเหลือ **{balance}**",
        "insufficient_funds": "❌ เงินไม่เพียงพอ ต้องการ **{price}** มี **{balance}**",
        "balance_title": "💰 ยอดเงิน",
        "your_balance_label": "ยอดเงินของคุณ",
        "shop_item_name_field": "ชื่อสินค้า",
        "shop_item_price_field": "ราคา",
        "shop_item_desc_field": "คำอธิบาย",
        "shop_item_cat_field": "หมวดหมู่",
        "shop_item_stock_field": "สต็อก (-1 = ไม่จำกัด)",
        "shop_item_restock_field": "รีสต็อกทุก (นาที, 0 = ไม่รีสต็อก)",
        "items_title": "📦 รายการไอเทม",
        "item_when_use_field": "ข้อความเมื่อใช้ (ว่าง = ใช้ไม่ได้)",
        "item_image_field": "URL รูปภาพ (ไม่บังคับ)",
        "material_tag": "📦 วัสดุ",
        "usable_tag": "✅ ใช้ได้",
        "shifter_admin_title": "⚙️ แผงแอดมินผู้แปลงร่าง",
        "grant_btn": "ให้สิทธิ์",
        "revoke_btn": "เพิกถอน",
        "tracker_btn": "ติดตาม",
        "set_time_btn": "ตั้งเวลา",
        "buy_btn": "🛒 ซื้อ",
        "buy_confirm": "ยืนยันการซื้อ **{item}** ราคา **{price}** หรือไม่?",
        "confirm_btn2": "✅ ยืนยัน",
        "cancel_btn": "❌ ยกเลิก",
        "restock_label": "เติมสต็อก: {interval}",
        "unlimited_stock": "ไม่จำกัด",
        "shop_channel_set": "เลือกช่องทาง",
        "add_image_btn": "เพิ่มรูปภาพ",
        "detransform_hidden": "🔄 ไทแทนได้ถอยร่างแล้ว",
        "ability_used_hidden": "⚔️ ไทแทนใช้ **{ability}**!",
        "transform_cooldown_msg": "⏳ การแปลงร่างอยู่ในช่วงคูลดาวน์อีก **{mins}** นาที",
        "ability_pending_config": "⚙️ ทักษะนี้รอการตั้งค่าจากแอดมิน ยังไม่สามารถใช้ได้",
        "show_profile_btn": "📋 แสดงโปรไฟล์",
        "manage_faction_roles_btn": "จัดการสังกัดและยศ",
        "grant_rank_btn": "ให้ยศพิเศษ",
        "got_rank_dm": "✨ คุณได้รับสิทธิ์ยศ **{rank}** ใน **{faction}** แล้ว! ใช้ `/profile` เพื่ออัปเดต",
        "mission_title": "📋 ภารกิจ",
        "create_mission_btn": "สร้างภารกิจใหม่",
        "no_missions": "ยังไม่มีภารกิจ",
        "join_mission_btn": "⚔️ เข้าร่วม",
        "view_players_btn": "👥 ดูรายชื่อ",
        "mission_joined": "✅ เข้าร่วมภารกิจ **{name}** แล้ว!",
        "mission_full": "❌ ภารกิจนี้เต็มแล้ว ({max} คน)",
        "already_joined_mission": "❌ คุณเข้าร่วมภารกิจนี้แล้ว",
        "finish_mission_btn": "✅ จบภารกิจ",
        "mission_log_field": "บันทึกเหตุการณ์ในภารกิจ",
        "mission_completed": "✅ ภารกิจ **{name}** เสร็จสมบูรณ์!",
        "configure_drops_btn": "🎁 ตั้งค่ารางวัล",
        "drop_for_all_btn": "รางวัลสำหรับทุกคน",
        "drop_for_player_btn": "รางวัลเฉพาะบุคคล",
        "mission_name_field": "ชื่อภารกิจ",
        "mission_desc_field": "คำอธิบาย",
        "mission_max_field": "จำนวนผู้เล่นสูงสุด (0=ไม่จำกัด)",
        "mission_admin_title": "⚔️ แผงแอดมินภารกิจ",
        "mission_players_title": "👥 ผู้เข้าร่วมภารกิจ",
        "mission_notify_admin": "🔔 **{user}** เข้าร่วมภารกิจ **{mission}**!",
        "page_label": "หน้า {page}/{total}",
        "edit_mission_btn": "แก้ไข",
        "delete_mission_btn": "🗑️ ลบ",
        "mission_channels_btn": "ตั้งช่องโพสต์",
        "mission_log_channels_btn": "ตั้งช่องบันทึก",
        "not_registered_join": "❌ ต้องลงทะเบียนตัวละครก่อน",
        "mission_drop_item_field": "ชื่อไอเทม",
        "mission_drop_qty_field": "จำนวน",
        "mission_drop_added": "✅ เพิ่มรางวัลแล้ว",
        "mission_drop_given": "🎁 คุณได้รับ **{item}** × {qty} จากภารกิจ!",
        "job_title": "💼 งาน",
        "no_jobs": "ยังไม่มีงาน",
        "apply_job_btn": "📝 สมัครงาน",
        "job_applied": "✅ สมัครงาน **{name}** แล้ว! รอการอนุมัติ",
        "job_accepted": "✅ ได้รับการรับเข้าทำงาน **{name}** แล้ว!",
        "job_declined": "❌ การสมัครงาน **{name}** ถูกปฏิเสธ",
        "job_owner_title": "👔 แผงจัดการงาน",
        "job_admin_title": "⚙️ แผงแอดมินงาน",
        "create_job_btn": "สร้างงานใหม่",
        "job_name_field": "ชื่องาน",
        "job_desc_field": "คำอธิบาย",
        "job_owner_field": "ชื่อนายจ้าง",
        "job_salary_field": "รายได้",
        "job_mode_rp": "📝 โหมด RP (พิมพ์ในห้อง)",
        "job_mode_passive": "💤 รายได้อัตโนมัติ",
        "job_min_letters_field": "ตัวอักษรขั้นต่ำต่อรอบ",
        "job_cooldown_field": "คูลดาวน์ (วินาที)",
        "job_rp_reward_field": "รางวัลต่อรอบ",
        "job_passive_interval_field": "รับเงินทุกกี่วินาที",
        "job_passive_reward_field": "จำนวนเงินที่ได้",
        "job_notify_owner": "🔔 **{user}** ({char}) สมัครงาน **{job}**!\nใช้ `/job-owner` เพื่อจัดการ",
        "job_created": "✅ สร้างงาน **{name}** แล้ว",
        "job_rp_earned": "💰 ได้รับ **{amount}** จากงาน **{job}**!",
        "job_passive_earned": "💰 รายได้จากงาน **{job}**: +**{amount}**!",
        "job_all_active": "งานทั้งหมด",
        "select_applicant": "เลือกผู้สมัคร",
        "no_applicants": "ยังไม่มีผู้สมัคร",
        "job_fired": "คุณถูกออกจากงาน **{job}**",
        "fire_employee_btn": "ไล่ออก",
        "xp_title": "⭐ ระดับและประสบการณ์",
        "xp_label": "XP",
        "level_label": "ระดับ",
        "level_up_msg": "🎉 ยินดีด้วย {name}! คุณขึ้นระดับเป็น **{level}** แล้ว!",
        "xp_progress_label": "ความคืบหน้า",
        "next_level_label": "ระดับถัดไปที่",
        "xp_gained": "✨ +{amount} XP จาก {reason}",
        "squad_title": "⚔️ หน่วยรบ",
        "create_squad_btn": "สร้างหน่วยรบ",
        "squad_name_field": "ชื่อหน่วยรบ",
        "squad_invite_btn": "📩 เชิญสมาชิก",
        "squad_kick_btn": "👢 ไล่ออก",
        "squad_promote_btn": "⬆️ เลื่อนตำแหน่ง",
        "squad_disband_btn": "💥 ยุบหน่วย",
        "squad_leave_btn": "🚪 ออกจากหน่วย",
        "squad_punish_btn": "⚠️ ลงโทษ",
        "squad_joined_msg": "✅ **{user}** เข้าร่วมหน่วย **{squad}** แล้ว!",
        "squad_kicked_msg": "👢 **{user}** ถูกไล่ออกจากหน่วย **{squad}**!",
        "squad_disbanded_msg": "💥 หน่วย **{squad}** ถูกยุบแล้ว!",
        "squad_invite_sent": "✅ ส่งคำเชิญไปยัง {user} แล้ว",
        "squad_invite_dm": "📩 คุณได้รับคำเชิญเข้าหน่วยรบ **{squad}**!\nใช้ `/squad` เพื่อตอบรับ",
        "squad_full_msg": "❌ หน่วยรบเต็มแล้ว ({max} คน)",
        "squad_wrong_faction": "❌ ต้องอยู่สังกัดเดียวกับผู้นำ ({faction})",
        "squad_no_perm": "❌ ต้องมียศ {ranks} ขึ้นไปจึงจะสร้างหน่วยรบได้",
        "squad_pending_invites_btn": "📩 คำเชิญที่รอดำเนินการ",
        "squad_accept_btn": "✅ ยอมรับ",
        "squad_decline_btn": "❌ ปฏิเสธ",
        "no_squad": "คุณไม่ได้อยู่ในหน่วยรบ",
        "squad_no_invite": "ไม่มีคำเชิญที่รอดำเนินการ",
        "squad_members_label": "สมาชิก",
        "squad_title_label": "ตำแหน่ง",
        "squad_faction_label": "สังกัด",
        "squad_promote_title_field": "ตำแหน่งใหม่",
        "squad_punish_msg": "⚠️ **{user}** ได้รับการลงโทษในหน่วย **{squad}**: {reason}",
        "squad_punish_reason_field": "เหตุผล",
        "squad_already_member": "❌ คุณอยู่ในหน่วยรบแล้ว",
        "squad_leave_confirm": "คุณออกจากหน่วย **{squad}** แล้ว",
        "squad_already_invited": "❌ ผู้เล่นคนนี้ได้รับคำเชิญแล้ว",
        "mindless_title": "🧟 ไทแทนที่ไร้สติ",
        "mindless_grab_btn": "✊ คว้า/จับ",
        "mindless_eat_btn": "🦷 กิน",
        "mindless_transform_msg": "⚡ **{name}** กลายเป็นไทแทนที่ไร้สติ!",
        "mindless_grab_msg": "✊ **{name}** คว้า **{target}**!",
        "mindless_eat_ask_body": "**{eater}** กำลังจะกินคุณ! คุณยอมรับหรือไม่?",
        "mindless_eat_accept_btn": "✅ ยอมรับ",
        "mindless_eat_decline_btn": "❌ ปฏิเสธ",
        "mindless_ate_shifter_msg": "💀 **{eater}** กิน **{target}** และได้รับพลัง **{titan}**!",
        "mindless_ate_normal_msg": "💀 **{eater}** กิน **{target}**!",
        "mindless_power_guide": "⚡ คุณได้รับพลัง **{titan}** จากการกิน!\n\nใช้ `/shifter` เพื่อเริ่มใช้พลัง",
        "mindless_no_perm": "❌ คุณไม่ได้อยู่ในสถานะไทแทนที่ไร้สติ",
        "mindless_inject_confirm_text": "ยืนยันฉีดยา **{target}** ให้กลายเป็นไทแทนที่ไร้สติ?",
        "mindless_inject_msg": "💉 **{user}** ถูกฉีดยาจาก **{injector}** และกลายเป็นไทแทนที่ไร้สติ!",
        "mindless_no_syringe": "❌ คุณไม่มีหลอดฉีดยา ({item})",
        "mindless_no_fluid": "❌ คุณไม่มีของเหลว ({item})",
        "eat_reason_field": "เหตุผลในการปฏิเสธ",
        "mindless_eat_refused": "❌ **{target}** ปฏิเสธ: {reason}",
        "select_target": "เลือกเป้าหมาย",
        "grab_btn": "✊ คว้า/จับ",
        "eat_btn": "🦷 กิน",
        "shifter_grab_msg": "✊ **{name}** คว้า **{target}**!",
        "shifter_eat_ask_body": "**{eater}** กำลังจะกินคุณ! คุณยอมรับหรือไม่?",
        "shifter_ate_shifter_msg": "💀 **{eater}** กิน **{target}** และได้รับพลัง **{titan}**!",
        "shifter_ate_normal_msg": "💀 **{eater}** กิน **{target}**!",
        "upgrade_ability_btn": "⬆️ อัปเกรดทักษะ",
        "upgrade_title": "⬆️ อัปเกรดทักษะ",
        "upgrade_cd_btn": "⏱ ลดคูลดาวน์ (-5m)",
        "upgrade_cost_btn": "💪 ลดค่าพลังงาน (-5)",
        "upgrade_not_enough": "❌ เงินไม่พอ ต้องการ {cost}",
        "upgrade_done": "✅ อัปเกรดสำเร็จ!",
        "customize_form_btn": "🎨 ปรับแต่งรูปร่าง",
        "customize_form_title": "🎨 ปรับแต่งรูปร่างไทแทน",
        "form_display_name_field": "ชื่อที่แสดง (ว่าง = ใช้ชื่อเดิม)",
        "form_image_field": "URL รูปภาพ (ไม่บังคับ)",
        "form_desc_field": "คำอธิบายรูปร่าง (ไม่บังคับ)",
        "form_saved": "✅ บันทึกการปรับแต่งรูปร่างแล้ว",
        "backstory_tab": "📖 ประวัติ",
        "journal_tab": "📔 บันทึก",
        "backstory_empty": "ยังไม่มีประวัติตัวละคร",
        "journal_empty": "ยังไม่มีบันทึก",
        "add_journal_btn": "➕ เพิ่มบันทึก",
        "edit_backstory_btn": "✏️ แก้ไขประวัติ",
        "journal_entry_field": "เนื้อหาบันทึก",
        "journal_public_btn": "🌐 สาธารณะ",
        "journal_private_btn": "🔒 ส่วนตัว",
        "journal_delete_btn": "🗑️ ลบ",
        "backstory_field": "ประวัติตัวละคร",
        "logs_setup_title": "📊 ตั้งค่าระบบบันทึก",
        "logs_channel_label": "ช่องทางบันทึก",
        "create_logs_channel_btn": "🔧 สร้างช่องทางบันทึก",
        "set_logs_channel_btn": "📌 กำหนดช่องทาง",
        "logs_channel_set_msg": "✅ ตั้งค่าช่องทางบันทึกแล้ว",
        "logs_channel_created_msg": "✅ สร้างช่องทางบันทึก #{name} แล้ว",
        "logs_no_channel": "❌ ยังไม่ได้ตั้งค่าช่องทางบันทึก",
        "logs_categories_btn": "📂 หมวดหมู่",
        "view_logs_btn": "👁️ ดูบันทึก",
        "no_logs_entries": "ยังไม่มีบันทึก",
        "backup_title": "💾 สำรองข้อมูล",
        "backup_create_btn": "📦 สร้างไฟล์สำรอง",
        "backup_restore_btn": "🔄 กู้คืนข้อมูล",
        "backup_created_msg": "✅ สร้างไฟล์สำรองสำเร็จ",
        "backup_restored_msg": "✅ กู้คืนข้อมูลสำเร็จ",
        "backup_upload_prompt": "อัปโหลดไฟล์สำรอง (.zip) ในข้อความถัดไปภายใน 60 วินาที",
        "backup_invalid_file": "❌ ไม่พบไฟล์หรือรูปแบบไม่ถูกต้อง",
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
        "config_title": "Configuration",
        "config_page": "Page {page}/{total}",
        "prev_btn": "◀ Prev",
        "next_btn": "Next ▶",
        "general_page": "🔧 General",
        "roles_page": "🎭 Roles",
        "lists_page": "📋 Lists",
        "permissions_page": "🔑 Permissions",
        "language_section": "🌐 Language",
        "currency_section": "💰 Currency",
        "ann_channels_section": "📢 Announcement Channels",
        "configure_btn": "Configure",
        "currency_name_field": "Currency Name",
        "currency_emoji_field": "Emoji (optional)",
        "currency_img_field": "Image URL (optional)",
        "announcement_title": "📢 Announcements",
        "create_draft_btn": "Create Draft",
        "no_drafts": "No drafts yet.",
        "draft_name_field": "Announcement Name",
        "draft_created": "✅ Draft **{name}** created.",
        "edit_title_btn": "Edit Title",
        "edit_content_btn": "Edit Content",
        "publish_btn": "🚀 Publish",
        "delete_draft_btn": "🗑️ Delete",
        "ann_title_field": "Title",
        "ann_content_field": "Content",
        "ann_published": "📢 Published!",
        "no_ann_channels": "❌ No announcement channels configured. Use /config page 1 to set them.",
        "ann_no_permission": "❌ You don't have permission to use this command.",
        "ann_permitted_roles_section": "🔑 Announcement Permissions",
        "shop_title": "🏪 Shop",
        "shop_setup_title": "Setup New Shop",
        "shop_config_title": "Shop Config",
        "no_shops": "No shops yet.",
        "shop_name_field": "Shop Name",
        "shop_owner_field": "Owner",
        "shop_desc_field": "Shop Description",
        "style_channel": "Channel",
        "style_thread": "Thread",
        "style_forum": "Forum",
        "shop_created": "✅ Shop **{name}** created.",
        "shop_img_field": "Image URL (optional)",
        "out_of_stock_label": "Out of Stock",
        "purchase_success": "✅ Purchased **{item}** for **{price}**. Balance: **{balance}**",
        "insufficient_funds": "❌ Insufficient funds. Need **{price}**, have **{balance}**.",
        "balance_title": "💰 Balance",
        "your_balance_label": "Your Balance",
        "shop_item_name_field": "Item Name",
        "shop_item_price_field": "Price",
        "shop_item_desc_field": "Description",
        "shop_item_cat_field": "Category",
        "shop_item_stock_field": "Stock (-1 = unlimited)",
        "shop_item_restock_field": "Restock every (min, 0 = never)",
        "items_title": "📦 Item List",
        "item_when_use_field": "When Used Message (empty = material item)",
        "item_image_field": "Image URL (optional)",
        "material_tag": "📦 Material",
        "usable_tag": "✅ Usable",
        "shifter_admin_title": "⚙️ Shifter Admin Panel",
        "grant_btn": "Grant",
        "revoke_btn": "Revoke",
        "tracker_btn": "Tracker",
        "set_time_btn": "Set Time",
        "buy_btn": "🛒 Buy",
        "buy_confirm": "Confirm purchasing **{item}** for **{price}**?",
        "confirm_btn2": "✅ Confirm",
        "cancel_btn": "❌ Cancel",
        "restock_label": "Restock: {interval}",
        "unlimited_stock": "Unlimited",
        "shop_channel_set": "Select Channel",
        "add_image_btn": "Add Image",
        "detransform_hidden": "🔄 The titan has retreated.",
        "ability_used_hidden": "⚔️ The titan uses **{ability}**!",
        "transform_cooldown_msg": "⏳ Transform on cooldown — **{mins}** minutes remaining.",
        "ability_pending_config": "⚙️ This ability is pending admin configuration and cannot be used yet.",
        "show_profile_btn": "📋 Show Profile",
        "manage_faction_roles_btn": "Manage Faction Roles",
        "grant_rank_btn": "Grant Hidden Rank",
        "got_rank_dm": "✨ You've been granted **{rank}** rank in **{faction}**! Use `/profile` to update.",
        "mission_title": "📋 Missions",
        "create_mission_btn": "Create Mission",
        "no_missions": "No missions available.",
        "join_mission_btn": "⚔️ Join",
        "view_players_btn": "👥 View Players",
        "mission_joined": "✅ Joined mission **{name}**!",
        "mission_full": "❌ Mission is full ({max} players).",
        "already_joined_mission": "❌ You already joined this mission.",
        "finish_mission_btn": "✅ Finish Mission",
        "mission_log_field": "Mission Log (what happened)",
        "mission_completed": "✅ Mission **{name}** completed!",
        "configure_drops_btn": "🎁 Configure Drops",
        "drop_for_all_btn": "Drop for All",
        "drop_for_player_btn": "Drop for Specific Player",
        "mission_name_field": "Mission Name",
        "mission_desc_field": "Description",
        "mission_max_field": "Max Players (0 = unlimited)",
        "mission_admin_title": "⚔️ Mission Admin Panel",
        "mission_players_title": "👥 Mission Players",
        "mission_notify_admin": "🔔 **{user}** joined mission **{mission}**!",
        "page_label": "Page {page}/{total}",
        "edit_mission_btn": "Edit",
        "delete_mission_btn": "🗑️ Delete",
        "mission_channels_btn": "Set Post Channels",
        "mission_log_channels_btn": "Set Log Channels",
        "not_registered_join": "❌ You must register a character first.",
        "mission_drop_item_field": "Item Name",
        "mission_drop_qty_field": "Quantity",
        "mission_drop_added": "✅ Drop added.",
        "mission_drop_given": "🎁 You received **{item}** × {qty} from the mission!",
        "job_title": "💼 Jobs",
        "no_jobs": "No jobs available.",
        "apply_job_btn": "📝 Apply",
        "job_applied": "✅ Applied for **{name}**! Awaiting approval.",
        "job_accepted": "✅ You were accepted for **{name}**!",
        "job_declined": "❌ Your application for **{name}** was declined.",
        "job_owner_title": "👔 Job Owner Panel",
        "job_admin_title": "⚙️ Job Admin Panel",
        "create_job_btn": "Create Job",
        "job_name_field": "Job Name",
        "job_desc_field": "Description",
        "job_owner_field": "Owner Name",
        "job_salary_field": "Salary",
        "job_mode_rp": "📝 RP Mode (earn by typing)",
        "job_mode_passive": "💤 Passive Income",
        "job_min_letters_field": "Min letters per round",
        "job_cooldown_field": "Cooldown (seconds)",
        "job_rp_reward_field": "Reward per round",
        "job_passive_interval_field": "Earn every N seconds",
        "job_passive_reward_field": "Amount earned",
        "job_notify_owner": "🔔 **{user}** ({char}) applied for **{job}**!\nUse `/job-owner` to manage.",
        "job_created": "✅ Job **{name}** created.",
        "job_rp_earned": "💰 Earned **{amount}** from job **{job}**!",
        "job_passive_earned": "💰 Passive income from **{job}**: +**{amount}**!",
        "job_all_active": "All Active Jobs",
        "select_applicant": "Select Applicant",
        "no_applicants": "No applicants yet.",
        "job_fired": "You were let go from job **{job}**.",
        "fire_employee_btn": "Fire Employee",
        "xp_title": "⭐ Level & Experience",
        "xp_label": "XP",
        "level_label": "Level",
        "level_up_msg": "🎉 Congratulations {name}! You reached **Level {level}**!",
        "xp_progress_label": "Progress",
        "next_level_label": "Next level at",
        "xp_gained": "✨ +{amount} XP from {reason}",
        "squad_title": "⚔️ Squad",
        "create_squad_btn": "Create Squad",
        "squad_name_field": "Squad Name",
        "squad_invite_btn": "📩 Invite Member",
        "squad_kick_btn": "👢 Kick",
        "squad_promote_btn": "⬆️ Promote",
        "squad_disband_btn": "💥 Disband",
        "squad_leave_btn": "🚪 Leave Squad",
        "squad_punish_btn": "⚠️ Punish",
        "squad_joined_msg": "✅ **{user}** joined squad **{squad}**!",
        "squad_kicked_msg": "👢 **{user}** was kicked from squad **{squad}**!",
        "squad_disbanded_msg": "💥 Squad **{squad}** has been disbanded!",
        "squad_invite_sent": "✅ Invite sent to {user}.",
        "squad_invite_dm": "📩 You've been invited to join squad **{squad}**!\nUse `/squad` to respond.",
        "squad_full_msg": "❌ Squad is full ({max} members).",
        "squad_wrong_faction": "❌ You must be in the same faction as the leader ({faction}).",
        "squad_no_perm": "❌ You need rank {ranks} to create a squad.",
        "squad_pending_invites_btn": "📩 Pending Invites",
        "squad_accept_btn": "✅ Accept",
        "squad_decline_btn": "❌ Decline",
        "no_squad": "You are not in a squad.",
        "squad_no_invite": "No pending invites.",
        "squad_members_label": "Members",
        "squad_title_label": "Title",
        "squad_faction_label": "Faction",
        "squad_promote_title_field": "New Title",
        "squad_punish_msg": "⚠️ **{user}** was punished in squad **{squad}**: {reason}",
        "squad_punish_reason_field": "Reason",
        "squad_already_member": "❌ You are already in a squad.",
        "squad_leave_confirm": "You left squad **{squad}**.",
        "squad_already_invited": "❌ This player was already invited.",
        "mindless_title": "🧟 Mindless Titan",
        "mindless_grab_btn": "✊ Grab",
        "mindless_eat_btn": "🦷 Eat",
        "mindless_transform_msg": "⚡ **{name}** has become a Mindless Titan!",
        "mindless_grab_msg": "✊ **{name}** grabs **{target}**!",
        "mindless_eat_ask_body": "**{eater}** is trying to eat you! Do you accept?",
        "mindless_eat_accept_btn": "✅ Accept",
        "mindless_eat_decline_btn": "❌ Refuse",
        "mindless_ate_shifter_msg": "💀 **{eater}** ate **{target}** and gained the **{titan}** power!",
        "mindless_ate_normal_msg": "💀 **{eater}** ate **{target}**!",
        "mindless_power_guide": "⚡ You received the **{titan}** power!\n\nUse `/shifter` to start using your power.",
        "mindless_no_perm": "❌ You are not a Mindless Titan.",
        "mindless_inject_confirm_text": "Confirm injecting **{target}** to become a Mindless Titan?",
        "mindless_inject_msg": "💉 **{user}** was injected by **{injector}** and became a Mindless Titan!",
        "mindless_no_syringe": "❌ You don't have the syringe ({item}).",
        "mindless_no_fluid": "❌ You don't have the fluid ({item}).",
        "eat_reason_field": "Reason for refusing",
        "mindless_eat_refused": "❌ **{target}** refused: {reason}",
        "select_target": "Select Target",
        "grab_btn": "✊ Grab",
        "eat_btn": "🦷 Eat",
        "shifter_grab_msg": "✊ **{name}** grabs **{target}**!",
        "shifter_eat_ask_body": "**{eater}** is trying to eat you! Do you accept?",
        "shifter_ate_shifter_msg": "💀 **{eater}** ate **{target}** and gained the **{titan}** power!",
        "shifter_ate_normal_msg": "💀 **{eater}** ate **{target}**!",
        "upgrade_ability_btn": "⬆️ Upgrade Ability",
        "upgrade_title": "⬆️ Upgrade Ability",
        "upgrade_cd_btn": "⏱ Reduce Cooldown (-5m)",
        "upgrade_cost_btn": "💪 Reduce Stamina Cost (-5)",
        "upgrade_not_enough": "❌ Insufficient funds. Need {cost}.",
        "upgrade_done": "✅ Upgrade successful!",
        "customize_form_btn": "🎨 Customize Form",
        "customize_form_title": "🎨 Customize Titan Form",
        "form_display_name_field": "Display Name (empty = use titan name)",
        "form_image_field": "Image URL (optional)",
        "form_desc_field": "Form description (optional)",
        "form_saved": "✅ Form customization saved.",
        "backstory_tab": "📖 Backstory",
        "journal_tab": "📔 Journal",
        "backstory_empty": "No backstory yet.",
        "journal_empty": "No journal entries yet.",
        "add_journal_btn": "➕ Add Entry",
        "edit_backstory_btn": "✏️ Edit Backstory",
        "journal_entry_field": "Journal Entry",
        "journal_public_btn": "🌐 Public",
        "journal_private_btn": "🔒 Private",
        "journal_delete_btn": "🗑️ Delete",
        "backstory_field": "Backstory",
        "logs_setup_title": "📊 Logs Setup",
        "logs_channel_label": "Logs Channel",
        "create_logs_channel_btn": "🔧 Create Logs Channel",
        "set_logs_channel_btn": "📌 Set Channel",
        "logs_channel_set_msg": "✅ Logs channel set.",
        "logs_channel_created_msg": "✅ Created logs channel #{name}.",
        "logs_no_channel": "❌ No logs channel configured.",
        "logs_categories_btn": "📂 Categories",
        "view_logs_btn": "👁️ View Logs",
        "no_logs_entries": "No logs yet.",
        "backup_title": "💾 Backup & Restore",
        "backup_create_btn": "📦 Create Backup",
        "backup_restore_btn": "🔄 Restore Backup",
        "backup_created_msg": "✅ Backup created successfully.",
        "backup_restored_msg": "✅ Data restored successfully.",
        "backup_upload_prompt": "Upload the backup .zip file in your next message within 60 seconds.",
        "backup_invalid_file": "❌ No valid file found or invalid format.",
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
    return _load_json(DATA_DIR / f"aot_players_{guild_id}.json", dict)

def save_players(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_players_{guild_id}.json", data)

def load_config(guild_id: int) -> dict:
    raw = _load_json(DATA_DIR / f"aot_config_{guild_id}.json", dict)
    merged = {**DEFAULT_CONFIG, **raw}
    for rtype in ("faction", "rank", "shifter", "bloodline"):
        merged["roles"].setdefault(rtype, {})
    return merged

def save_config(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_config_{guild_id}.json", data)

def load_items(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"aot_items_{guild_id}.json",
                      lambda: {"categories": {}, "category_order": [], "items": {}})

def save_items(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_items_{guild_id}.json", data)

def load_announcements(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"aot_announcements_{guild_id}.json", lambda: {"drafts": {}})

def save_announcements(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_announcements_{guild_id}.json", data)

def load_shops(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"aot_shops_{guild_id}.json", lambda: {"shops": {}})

def save_shops(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_shops_{guild_id}.json", data)

def load_missions(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"aot_missions_{guild_id}.json", lambda: {"missions": {}})

def save_missions(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_missions_{guild_id}.json", data)

def load_jobs(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"aot_jobs_{guild_id}.json", lambda: {"jobs": {}})

def save_jobs(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_jobs_{guild_id}.json", data)

def load_squads(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"aot_squads_{guild_id}.json", lambda: {"squads": {}})

def save_squads(guild_id: int, data: dict):
    _save_json(DATA_DIR / f"aot_squads_{guild_id}.json", data)

def load_logs_data(guild_id: int) -> dict:
    return _load_json(DATA_DIR / f"aot_logs_{guild_id}.json", lambda: {"entries": []})


# ── Utilities ─────────────────────────────────────────────────────────────────

def save_logs_data(guild_id: int, data: dict):
    entries = data.get("entries", [])
    if len(entries) > 500:
        data["entries"] = entries[-500:]
    _save_json(DATA_DIR / f"aot_logs_{guild_id}.json", data)


async def log_event(bot_instance, guild_id: int, category: str, text: str) -> None:
    import time as _time, discord as _d
    cfg = load_config(guild_id)
    cats = cfg.get("logs_categories", {})
    if cats and not cats.get(category, True):
        return
    data = load_logs_data(guild_id)
    data["entries"].append({"category": category, "text": text, "ts": _time.time()})
    save_logs_data(guild_id, data)
    ch_id = cfg.get("logs_channel")
    if not ch_id:
        return
    for g in bot_instance.guilds:
        if g.id == guild_id:
            ch = g.get_channel(int(ch_id))
            if ch:
                try:
                    v = _d.ui.LayoutView(timeout=None)
                    v.add_item(_d.ui.Container(_d.ui.TextDisplay(f"[{category.upper()}] {text}")))
                    await ch.send(view=v)
                except Exception:
                    pass
            break


def add_xp(guild_id: int, user_id: int, amount: int) -> tuple:
    players = load_players(guild_id)
    player  = players.get(str(user_id), {})
    if not player:
        return (0, 1, False)
    old_level = _get_level(player.get("xp", 0))
    player["xp"] = player.get("xp", 0) + amount
    new_level    = _get_level(player["xp"])
    leveled_up   = new_level > old_level
    if leveled_up:
        player["level"] = new_level
    players[str(user_id)] = player
    save_players(guild_id, players)
    return (player["xp"], new_level, leveled_up)


def _get_level(xp: int) -> int:
    level = 1
    while xp >= _xp_for_level(level + 1):
        level += 1
        if level >= 100:
            break
    return level


def _xp_for_level(level: int) -> int:
    return 100 * (level ** 2)


def format_full_player_info(player: dict, display_name: str, guild_id: int) -> str:
    lines = [
        f"**Discord:** {display_name}",
        f"**{t(guild_id,'name_label')}:** {player.get('name','?')}",
        f"**{t(guild_id,'age_label')}:** {player.get('age','?')}",
        f"**{t(guild_id,'gender_label')}:** {player.get('gender','?')}",
        f"**{t(guild_id,'faction_label')}:** {player.get('faction','?')}",
        f"**{t(guild_id,'rank_label')}:** {player.get('rank','?')}",
        f"**{t(guild_id,'bloodline_label')}:** {player.get('bloodline','?')}",
        f"**{t(guild_id,'balance_label')}:** {player.get('balance',0)}",
    ]
    inv = player.get("inventory", {})
    if inv:
        items_data = load_items(guild_id)
        all_items  = items_data.get("items", {})
        inv_lines  = [f"  • {all_items.get(iid,{}).get('name',iid)} × {qty}"
                      for iid, qty in list(inv.items())[:10] if qty > 0]
        if inv_lines:
            lines.append(f"**{t(guild_id,'inventory_btn')}:**")
            lines += inv_lines
    return "\n".join(lines)


def get_player_squad(guild_id: int, user_id: int):
    db = load_squads(guild_id)
    for sid, sq in db.get("squads", {}).items():
        if str(user_id) in sq.get("members", {}):
            return sid, sq
    return None, None


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


def get_faction_names(guild_id: int) -> list:
    cfg = load_config(guild_id)
    frs = cfg.get("faction_roles", [])
    return [fr["name"] for fr in frs] if frs else cfg.get("factions", [])


def get_all_rank_names(guild_id: int) -> list:
    cfg = load_config(guild_id)
    frs = cfg.get("faction_roles", [])
    if not frs:
        return cfg.get("ranks", [])
    seen: set = set(); names: list = []
    for fr in frs:
        for r in fr.get("ranks", []):
            if r["name"] not in seen:
                seen.add(r["name"]); names.append(r["name"])
    return names


def get_visible_ranks_for_faction(guild_id: int, faction_name: str, user_id: int) -> list:
    cfg = load_config(guild_id)
    granted = set(cfg.get("rank_access", {}).get(str(user_id), []))
    for fr in cfg.get("faction_roles", []):
        if fr["name"] == faction_name:
            return [r["name"] for r in fr.get("ranks", [])
                    if r.get("visible", True) or r["name"] in granted]
    return cfg.get("ranks", [])


def get_faction_emblem(guild_id: int, faction_name: str) -> str:
    cfg = load_config(guild_id)
    for fr in cfg.get("faction_roles", []):
        if fr["name"] == faction_name:
            return fr.get("image", "").strip()
    return RANK_EMBLEMS.get(faction_name, "")



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

def format_currency(amount: int, cfg: dict) -> str:
    name  = cfg.get("currency_name", "Coins")
    emoji = cfg.get("currency_emoji", "").strip()
    prefix = f"{emoji} " if emoji else ""
    return f"{prefix}{amount} {name}"


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
