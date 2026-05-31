# ============================================================
# ORION — Auction / Black Market System
# ============================================================
# - Admin ตั้ง role ที่ลงประมูลได้
# - Admin ตั้ง channel/thread ที่ใช้ประมูล
# - ผู้ขายลงไอเทมจากกระเป๋า + ราคาเริ่มต้น
# - ผู้เล่นใช้ /ประมูล ยกราคาขึ้น
# - ผู้ขายปิดประมูลเอง → ผู้ชนะได้ของ ผู้ขายได้เงิน
# ============================================================

import sys
import time
import uuid as _uuid
import discord

_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_auction ต้องถูก import จาก orion_bot.py")

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

import orion_items
get_player_inv     = orion_items.get_player_inv
get_item           = orion_items.get_item
add_player_item    = orion_items.add_player_item
remove_player_item = orion_items.remove_player_item
load_items_catalog = orion_items.load_items_catalog


def _eph(name: str) -> bool:
    fn = getattr(_orion_bot_mod, "_eph", None)
    return True if fn is None else fn(name)


def _safe_emoji(s, default="📦"):
    fn = getattr(_orion_bot_mod, "_safe_emoji", None)
    return fn(s, default) if fn else default


AUCTION_CFG_FILE = f"{ORION_DATA_DIR}/auction_config.json"
AUCTIONS_FILE    = f"{ORION_DATA_DIR}/auctions.json"

DEFAULT_AUCTION_CFG = {
    "allowed_role_ids": [],       # role IDs ที่ลงประมูลได้ (ว่าง = แอดมินเท่านั้น)
    "auction_channel_id": 0,      # channel/thread ที่ใช้ประมูล (0 = ไม่จำกัด)
    "min_bid_increment": 1,       # bid ต้องเพิ่มขั้นต่ำเท่าไหร่
}


def load_auction_cfg() -> dict:
    cfg = load_json(AUCTION_CFG_FILE, {})
    changed = False
    for k, v in DEFAULT_AUCTION_CFG.items():
        if k not in cfg:
            cfg[k] = v; changed = True
    if changed:
        save_auction_cfg(cfg)
    return cfg


def save_auction_cfg(cfg):
    save_json(AUCTION_CFG_FILE, cfg)


def load_auctions() -> dict:
    return load_json(AUCTIONS_FILE, {})


def save_auctions(d):
    save_json(AUCTIONS_FILE, d)


def can_list_auction(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True
    cfg = load_auction_cfg()
    allowed = set(cfg.get("allowed_role_ids", []))
    if not allowed:
        return False
    return bool({r.id for r in member.roles} & allowed)


# ── Embeds ───────────────────────────────────────────────────
def _auction_embed(aid: str, a: dict) -> discord.Embed:
    cat = load_items_catalog()
    it = cat.get(a["item_id"], {})
    status = a.get("status", "active")
    color = 0x2ecc71 if status == "active" else 0x95a5a6
    title_prefix = "🔨" if status == "active" else "🏁"
    embed = discord.Embed(
        title=f"{title_prefix}  {it.get('emoji','📦')} {it.get('name','?')} ×{a.get('qty',1)}",
        description=it.get("description","")[:300] or "_ไม่มีคำอธิบาย_",
        color=color,
    )
    if it.get("image_url"):
        embed.set_thumbnail(url=it["image_url"])
    embed.add_field(name="👤 ผู้ขาย", value=f"<@{a['seller_id']}>", inline=True)
    embed.add_field(name="💰 ราคาเริ่มต้น", value=money_str(a.get("start_price",0)), inline=True)
    embed.add_field(name="📈 ราคาปัจจุบัน", value=money_str(a.get("current_bid", a.get("start_price",0))), inline=True)
    bidder = a.get("current_bidder_id")
    embed.add_field(name="🏆 ผู้นำการประมูล", value=(f"<@{bidder}>" if bidder else "_ยังไม่มีใครประมูล_"), inline=False)
    embed.add_field(name="📊 สถานะ", value=("🟢 เปิด" if status == "active" else "🔴 ปิดแล้ว"), inline=True)
    embed.add_field(name="🆔 Auction ID", value=f"`{aid}`", inline=True)
    embed.set_footer(text="Orion · Auction")
    return embed


# ── List item (เลือกของในกระเป๋า) ─────────────────────────────
class AuctionItemSelect(discord.ui.Select):
    def __init__(self, uid: str):
        self.uid = uid
        inv = get_player_inv(uid)[:25]
        cat = load_items_catalog()
        options = []
        for entry in inv:
            it = cat.get(entry["item_id"], {})
            options.append(discord.SelectOption(
                label=f"{it.get('name', entry['item_id'])} (×{entry.get('qty',1)})"[:100],
                value=entry["item_id"],
                description=(it.get("description","")[:80] or "—"),
                emoji=_safe_emoji(it.get("emoji")),
            ))
        if not options:
            options = [discord.SelectOption(label="กระเป๋าว่าง", value="none")]
        super().__init__(placeholder="📦 เลือกไอเทมที่จะลงประมูล...", options=options)

    async def callback(self, ix: discord.Interaction):
        if self.values[0] == "none":
            await ix.response.defer(); return
        await ix.response.send_modal(AuctionListModal(self.uid, self.values[0]))


class AuctionListView(discord.ui.View):
    def __init__(self, uid: str):
        super().__init__(timeout=180)
        self.add_item(AuctionItemSelect(uid))


class AuctionListModal(discord.ui.Modal, title="🔨 ลงประมูลไอเทม"):
    f_qty   = discord.ui.TextInput(label="จำนวน", placeholder="1", max_length=4)
    f_price = discord.ui.TextInput(label="ราคาเริ่มต้น (ตัวเลข)", placeholder="100", max_length=10)

    def __init__(self, uid: str, item_id: str):
        super().__init__()
        self.uid = uid
        self.item_id = item_id

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_auction_cfg()
        # check channel ถ้าตั้งไว้
        auction_ch = cfg.get("auction_channel_id", 0)
        if auction_ch and ix.channel and ix.channel.id != auction_ch:
            await ix.response.send_message(
                f"❌ ลงประมูลได้เฉพาะใน <#{auction_ch}> เท่านั้น", ephemeral=True,
            ); return
        qty = max(1, _parse_int(self.f_qty.value, 1) or 1)
        price = max(0, _parse_int(self.f_price.value, 0) or 0)
        # check inventory
        inv = {x["item_id"]: int(x.get("qty", 0)) for x in get_player_inv(self.uid)}
        if inv.get(self.item_id, 0) < qty:
            await ix.response.send_message(
                f"❌ คุณมีไอเทมนี้แค่ ×{inv.get(self.item_id, 0)} (จะลงประมูล ×{qty})",
                ephemeral=True,
            ); return
        # ยึดของจากกระเป๋า (escrow)
        remove_player_item(self.uid, self.item_id, qty)
        aid = _uuid.uuid4().hex[:8]
        auctions = load_auctions()
        auctions[aid] = {
            "seller_id": self.uid,
            "item_id":   self.item_id,
            "qty":       qty,
            "start_price": price,
            "current_bid": price,
            "current_bidder_id": None,
            "channel_id": ix.channel.id if ix.channel else 0,
            "status":    "active",
            "created_at": int(time.time()),
        }
        save_auctions(auctions)
        # post ลงห้อง
        await ix.response.send_message(
            content=f"🔨 **ประมูลใหม่!** (`/ประมูล {aid} <ราคา>` เพื่อยกราคา)",
            embed=_auction_embed(aid, auctions[aid]),
            ephemeral=False,   # post publicly in channel
        )


# ── Admin config ─────────────────────────────────────────────
class AuctionAdminRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="เลือก role ที่ลงประมูลได้...", min_values=0, max_values=10)

    async def callback(self, ix: discord.Interaction):
        cfg = load_auction_cfg()
        cfg["allowed_role_ids"] = [r.id for r in self.values]
        save_auction_cfg(cfg)
        names = ", ".join(r.mention for r in self.values) or "_(ว่าง — admin เท่านั้น)_"
        await ix.response.send_message(f"✅ ตั้ง role ลงประมูล: {names}", ephemeral=True)


class AuctionAdminChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="เลือกห้อง/เธรดประมูล...",
            channel_types=[discord.ChannelType.text, discord.ChannelType.public_thread, discord.ChannelType.private_thread],
            min_values=0, max_values=1,
        )

    async def callback(self, ix: discord.Interaction):
        cfg = load_auction_cfg()
        if not self.values:
            cfg["auction_channel_id"] = 0
            msg = "✅ ล้างห้องประมูล (ลงได้ทุกห้อง)"
        else:
            ch = self.values[0]
            cfg["auction_channel_id"] = ch.id
            msg = f"✅ ตั้งห้องประมูลเป็น <#{ch.id}>"
        save_auction_cfg(cfg)
        await ix.response.send_message(msg, ephemeral=True)


class AuctionSettingsModal(discord.ui.Modal, title="⚙️ ตั้งค่าประมูล"):
    f_min = discord.ui.TextInput(label="ราคา bid ขั้นต่ำที่ต้องเพิ่ม", placeholder="1", max_length=10)

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_auction_cfg()
        cfg["min_bid_increment"] = max(1, _parse_int(self.f_min.value, 1) or 1)
        save_auction_cfg(cfg)
        await ix.response.send_message(f"✅ bid ขั้นต่ำ: {cfg['min_bid_increment']}", ephemeral=True)


class AuctionAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.add_item(AuctionAdminRoleSelect())
        self.add_item(AuctionAdminChannelSelect())

    async def interaction_check(self, ix):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return False
        return True

    @discord.ui.button(label="ตั้งราคา bid ขั้นต่ำ", style=discord.ButtonStyle.primary, row=2)
    async def btn_min(self, ix, _b):
        await ix.response.send_modal(AuctionSettingsModal())

    @discord.ui.button(label="ดูประมูลทั้งหมด", style=discord.ButtonStyle.secondary, row=2)
    async def btn_list(self, ix, _b):
        auctions = load_auctions()
        if not auctions:
            await ix.response.send_message("_ยังไม่มีประมูล_", ephemeral=True); return
        cat = load_items_catalog()
        lines = []
        for aid, a in list(auctions.items())[:15]:
            it = cat.get(a["item_id"], {})
            lines.append(
                f"`{aid}` · {it.get('emoji','📦')} {it.get('name','?')} ×{a.get('qty',1)} · "
                f"{money_str(a.get('current_bid',0))} · {'🟢' if a.get('status')=='active' else '🔴'}"
            )
        embed = discord.Embed(title=f"📚 ประมูลทั้งหมด ({len(auctions)})", description="\n".join(lines)[:3000], color=0x95a5a6)
        await ix.response.send_message(embed=embed, ephemeral=True)


# ── Slash commands ───────────────────────────────────────────
@bot.tree.command(name="ลงประมูล", description="ลงไอเทมประมูล (เลือกจากกระเป๋า)", guild=_ORION_GUILD_OBJ)
async def cmd_auction_list(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not can_list_auction(interaction.user):
        await interaction.response.send_message("❌ คุณไม่มี role ที่อนุญาตให้ลงประมูล", ephemeral=True); return
    cfg = load_auction_cfg()
    auction_ch = cfg.get("auction_channel_id", 0)
    if auction_ch and interaction.channel and interaction.channel.id != auction_ch:
        await interaction.response.send_message(
            f"❌ ใช้คำสั่งนี้ได้เฉพาะใน <#{auction_ch}>", ephemeral=True,
        ); return
    uid = str(interaction.user.id)
    ensure_orion_player(uid)
    inv = get_player_inv(uid)
    if not inv:
        await interaction.response.send_message("❌ กระเป๋าว่าง", ephemeral=True); return
    await interaction.response.send_message(
        "📦 เลือกไอเทมจะลงประมูล ↓",
        view=AuctionListView(uid),
        ephemeral=True,
    )


@bot.tree.command(name="ประมูล", description="ยกราคาประมูล", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(auction_id="Auction ID", bid="ราคาที่ต้องการยก")
async def cmd_auction_bid(interaction: discord.Interaction, auction_id: str, bid: int):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    cfg = load_auction_cfg()
    auctions = load_auctions()
    a = auctions.get(auction_id)
    if not a:
        await interaction.response.send_message("❌ ไม่พบ Auction ID", ephemeral=True); return
    if a.get("status") != "active":
        await interaction.response.send_message("❌ ประมูลนี้ปิดไปแล้ว", ephemeral=True); return
    uid = str(interaction.user.id)
    if uid == a["seller_id"]:
        await interaction.response.send_message("❌ ผู้ขายประมูลของตัวเองไม่ได้", ephemeral=True); return
    cur = int(a.get("current_bid", a.get("start_price", 0)))
    min_inc = int(cfg.get("min_bid_increment", 1))
    if bid < cur + min_inc:
        await interaction.response.send_message(
            f"❌ ต้องยกอย่างน้อย {money_str(cur + min_inc)} (ปัจจุบัน {money_str(cur)}, ขั้นต่ำ +{min_inc})",
            ephemeral=True,
        ); return
    if get_wallet(uid) < bid:
        await interaction.response.send_message(
            f"❌ เงินไม่พอ — มี {money_str(get_wallet(uid))}", ephemeral=True,
        ); return
    # คืนเงินผู้นำคนเก่า (ถ้ามี)
    prev_bidder = a.get("current_bidder_id")
    prev_bid    = int(a.get("current_bid", 0)) if prev_bidder else 0
    if prev_bidder and prev_bidder != uid:
        add_money(prev_bidder, prev_bid)
    elif prev_bidder == uid:
        # ตัวเองยก: คืนเงินก่อนหน้าด้วย (ไม่งั้นจะหักซ้ำ)
        add_money(uid, prev_bid)
    # หักเงินผู้นำคนใหม่
    add_money(uid, -bid)
    a["current_bid"] = bid
    a["current_bidder_id"] = uid
    save_auctions(auctions)
    await interaction.response.send_message(
        f"📈 {interaction.user.mention} ยก **{auction_id}** เป็น {money_str(bid)}",
        embed=_auction_embed(auction_id, a),
        ephemeral=False,
    )


@bot.tree.command(name="ปิดประมูล", description="ปิดประมูลของตัวเอง (ผู้ชนะได้ของ ผู้ขายได้เงิน)", guild=_ORION_GUILD_OBJ)
@discord.app_commands.describe(auction_id="Auction ID")
async def cmd_auction_close(interaction: discord.Interaction, auction_id: str):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    auctions = load_auctions()
    a = auctions.get(auction_id)
    if not a:
        await interaction.response.send_message("❌ ไม่พบ Auction ID", ephemeral=True); return
    if a.get("status") != "active":
        await interaction.response.send_message("❌ ประมูลนี้ปิดไปแล้ว", ephemeral=True); return
    uid = str(interaction.user.id)
    is_admin = interaction.user.guild_permissions.administrator
    if uid != a["seller_id"] and not is_admin:
        await interaction.response.send_message("❌ เฉพาะผู้ขายหรือแอดมินเท่านั้น", ephemeral=True); return
    a["status"] = "closed"
    winner = a.get("current_bidder_id")
    bid    = int(a.get("current_bid", 0))
    item_id = a["item_id"]
    qty     = int(a.get("qty", 1))
    if winner:
        # ผู้ชนะได้ของ, ผู้ขายได้เงิน (เงินถูกถือไว้แล้วตอน bid)
        add_player_item(winner, item_id, qty)
        add_money(a["seller_id"], bid)
        result_text = (
            f"🏁 **ปิดประมูล `{auction_id}`!**\n"
            f"🏆 ผู้ชนะ: <@{winner}> ที่ {money_str(bid)}\n"
            f"💰 <@{a['seller_id']}> ได้รับ {money_str(bid)}\n"
            f"📦 <@{winner}> ได้รับไอเทม"
        )
    else:
        # ไม่มีคนประมูล → คืนของให้ผู้ขาย
        add_player_item(a["seller_id"], item_id, qty)
        result_text = f"🏁 **ปิดประมูล `{auction_id}`** — ไม่มีคนประมูล ของคืนให้ <@{a['seller_id']}>"
    save_auctions(auctions)
    await interaction.response.send_message(
        content=result_text,
        embed=_auction_embed(auction_id, a),
        ephemeral=False,
    )


@bot.tree.command(name="ดูประมูล", description="ดูประมูลที่กำลังเปิดอยู่", guild=_ORION_GUILD_OBJ)
async def cmd_auction_list_active(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    auctions = load_auctions()
    active = [(aid, a) for aid, a in auctions.items() if a.get("status") == "active"]
    if not active:
        await interaction.response.send_message("_ยังไม่มีประมูลเปิดอยู่_", ephemeral=_eph("ดูประมูล")); return
    cat = load_items_catalog()
    lines = []
    for aid, a in active[:15]:
        it = cat.get(a["item_id"], {})
        lines.append(
            f"`{aid}` · {it.get('emoji','📦')} {it.get('name','?')} ×{a.get('qty',1)} · "
            f"ปัจจุบัน {money_str(a.get('current_bid',0))} · ผู้ขาย <@{a['seller_id']}>"
        )
    embed = discord.Embed(
        title=f"🔨 ประมูลที่เปิดอยู่ ({len(active)})",
        description="\n".join(lines)[:3000] + "\n\n_ใช้ `/ประมูล <id> <ราคา>` เพื่อยก_",
        color=0x2ecc71,
    )
    await interaction.response.send_message(embed=embed, ephemeral=_eph("ดูประมูล"))


@bot.tree.command(name="ประมูลแอดมิน", description="[Admin] จัดการระบบประมูล", guild=_ORION_GUILD_OBJ)
async def cmd_auction_admin(interaction: discord.Interaction):
    if not interaction.guild or interaction.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        await interaction.response.send_message("❌ ใช้ได้เฉพาะในเซิร์ฟ Orion", ephemeral=True); return
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ ต้องเป็นแอดมิน", ephemeral=True); return
    cfg = load_auction_cfg()
    auctions = load_auctions()
    active_n = sum(1 for a in auctions.values() if a.get("status") == "active")
    roles_text = ", ".join(f"<@&{rid}>" for rid in cfg.get("allowed_role_ids", [])) or "_(ว่าง — admin เท่านั้น)_"
    ch_text = f"<#{cfg['auction_channel_id']}>" if cfg.get("auction_channel_id") else "_(ทุกห้อง)_"
    embed = discord.Embed(
        title="🔨  Auction — Admin Panel",
        description=(
            f"**Auction ทั้งหมด:** {len(auctions)} · **เปิดอยู่:** {active_n}\n"
            f"**Role ที่ลงได้:** {roles_text}\n"
            f"**ห้องประมูล:** {ch_text}\n"
            f"**Bid ขั้นต่ำที่ต้องเพิ่ม:** +{cfg.get('min_bid_increment',1)}\n\n"
            "**ตั้งค่า:** เลือก role + channel จาก dropdown ด้านล่าง"
        ),
        color=0x2ecc71,
    )
    await interaction.response.send_message(embed=embed, view=AuctionAdminView(), ephemeral=True)
