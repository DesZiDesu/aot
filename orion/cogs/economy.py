"""Orion — currency system: balance, transfer, admin grant/remove."""
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR,
    load_config, save_config,
    load_players, save_players,
    get_wallet, add_money, money_str, currency_cfg,
)


# ── /wallet ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="wallet", description="ดูจำนวนเงินของตัวเอง")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_wallet(ix: discord.Interaction):
    gid = ix.guild_id
    bal = get_wallet(gid, ix.user.id)
    embed = discord.Embed(
        title="💰 กระเป๋าเงิน",
        description=money_str(bal, gid),
        color=EMBED_COLOR,
    )
    await ix.response.send_message(embed=embed, ephemeral=True)


# ── /check-wallet ─────────────────────────────────────────────────────────────

@bot.tree.command(name="check-wallet", description="ดูเงินของผู้เล่นอื่น (หรือของตัวเอง)")
@app_commands.guilds(*GUILD_OBJECTS)
@app_commands.describe(member="ผู้เล่นที่ต้องการดู")
async def cmd_check_wallet(ix: discord.Interaction, member: discord.Member | None = None):
    gid    = ix.guild_id
    target = member or ix.user
    bal    = get_wallet(gid, target.id)
    embed  = discord.Embed(
        title=f"💰 เงินของ {target.display_name}",
        description=money_str(bal, gid),
        color=EMBED_COLOR,
    )
    await ix.response.send_message(embed=embed, ephemeral=True)


# ── /transfer ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="transfer", description="โอนเงินให้ผู้เล่นอื่น")
@app_commands.guilds(*GUILD_OBJECTS)
@app_commands.describe(member="ผู้รับ", amount="จำนวนเงิน")
async def cmd_transfer(ix: discord.Interaction, member: discord.Member, amount: int):
    gid = ix.guild_id
    uid = ix.user.id
    if member.id == uid:
        await ix.response.send_message("ไม่สามารถโอนให้ตัวเองได้", ephemeral=True)
        return
    if amount <= 0:
        await ix.response.send_message("จำนวนต้องมากกว่า 0", ephemeral=True)
        return
    bal = get_wallet(gid, uid)
    if bal < amount:
        await ix.response.send_message(
            f"เงินไม่พอ (มี {money_str(bal, gid)})", ephemeral=True
        )
        return
    view = TransferConfirmView(uid, gid, member.id, amount)
    embed = discord.Embed(
        title="💸 ยืนยันการโอน",
        description=(
            f"โอน **{money_str(amount, gid)}**\n"
            f"ไปให้ **{member.display_name}**?"
        ),
        color=0xF59E0B,
    )
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class TransferConfirmView(discord.ui.View):
    def __init__(self, sender_id: int, gid: int, receiver_id: int, amount: int):
        super().__init__(timeout=60)
        self.sender   = sender_id
        self.gid      = gid
        self.receiver = receiver_id
        self.amount   = amount

    @discord.ui.button(label="✅ ยืนยัน", style=discord.ButtonStyle.success)
    async def confirm(self, ix: discord.Interaction, _: discord.ui.Button):
        if ix.user.id != self.sender:
            await ix.response.send_message("นี่ไม่ใช่เซสชันของคุณ", ephemeral=True)
            return
        bal = get_wallet(self.gid, self.sender)
        if bal < self.amount:
            await ix.response.send_message("เงินไม่พอ", ephemeral=True)
            return
        add_money(self.gid, self.sender, -self.amount)
        add_money(self.gid, self.receiver, self.amount)
        embed = discord.Embed(
            description=f"✅ โอน {money_str(self.amount, self.gid)} ให้ <@{self.receiver}> แล้ว",
            color=discord.Color.green(),
        )
        await ix.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="❌ ยกเลิก", style=discord.ButtonStyle.danger)
    async def cancel(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.edit_message(
            embed=discord.Embed(description="ยกเลิก", color=EMBED_COLOR), view=None
        )


# ── /wallet-admin ─────────────────────────────────────────────────────────────

@bot.tree.command(name="wallet-admin", description="[Admin] จัดการเงินผู้เล่น + ตั้งค่าสกุลเงิน")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_wallet_admin(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    gid   = ix.guild_id
    view  = WalletAdminView(gid)
    embed = _wallet_admin_embed(gid)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


def _wallet_admin_embed(gid: int) -> discord.Embed:
    cc = currency_cfg(gid)
    embed = discord.Embed(title="💰 Wallet Admin", color=EMBED_COLOR)
    embed.add_field(name="ชื่อสกุลเงิน", value=cc["name"],  inline=True)
    embed.add_field(name="Emoji",         value=cc["emoji"], inline=True)
    return embed


class WalletAdminView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    @discord.ui.button(label="➕ ให้เงิน", style=discord.ButtonStyle.success, row=0)
    async def btn_give(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_message(
            embed=discord.Embed(description="เลือกผู้เล่นที่จะให้เงิน:", color=EMBED_COLOR),
            view=_GiveMoneySelectView(self.gid, "give"),
            ephemeral=True,
        )

    @discord.ui.button(label="➖ หักเงิน", style=discord.ButtonStyle.danger, row=0)
    async def btn_take(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_message(
            embed=discord.Embed(description="เลือกผู้เล่นที่จะหักเงิน:", color=EMBED_COLOR),
            view=_GiveMoneySelectView(self.gid, "take"),
            ephemeral=True,
        )

    @discord.ui.button(label="⚙️ ตั้งสกุลเงิน", style=discord.ButtonStyle.secondary, row=1)
    async def btn_currency(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(CurrencySettingsModal(self.gid))


class _GiveMoneySelectView(discord.ui.View):
    def __init__(self, gid: int, mode: str):
        super().__init__(timeout=120)
        self.gid  = gid
        self.mode = mode
        sel = discord.ui.UserSelect(placeholder="เลือกผู้เล่น…", row=0)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        target = int(ix.data["values"][0])
        await ix.response.send_modal(GiveMoneyModal(self.gid, target, self.mode))


class GiveMoneyModal(discord.ui.Modal, title="จำนวนเงิน"):
    amount = discord.ui.TextInput(label="จำนวน", max_length=12)

    def __init__(self, gid: int, target_id: int, mode: str):
        super().__init__()
        self.gid       = gid
        self.target_id = target_id
        self.mode      = mode

    async def on_submit(self, ix: discord.Interaction):
        try:
            val = max(0, int(self.amount.value.strip()))
        except ValueError:
            await ix.response.send_message("ตัวเลขไม่ถูกต้อง", ephemeral=True)
            return
        delta = val if self.mode == "give" else -val
        add_money(self.gid, self.target_id, delta)
        sign = "+" if self.mode == "give" else "-"
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ {sign}{money_str(val, self.gid)} → <@{self.target_id}>",
                color=EMBED_COLOR,
            ),
            ephemeral=True,
        )


class CurrencySettingsModal(discord.ui.Modal, title="ตั้งค่าสกุลเงิน"):
    name_f  = discord.ui.TextInput(label="ชื่อสกุลเงิน", max_length=30)
    emoji_f = discord.ui.TextInput(label="Emoji", max_length=10)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        cc = currency_cfg(gid)
        self.name_f.default  = cc["name"]
        self.emoji_f.default = cc["emoji"]

    async def on_submit(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        cfg["currency_name"]  = self.name_f.value.strip()
        cfg["currency_emoji"] = self.emoji_f.value.strip()
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(description="✅ บันทึกสกุลเงินแล้ว", color=EMBED_COLOR),
            ephemeral=True,
        )
