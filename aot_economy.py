"""Economy system — balance, transfer, admin money management."""
import discord
from discord import app_commands

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import t, load_players, save_players, load_config, format_currency, log_event


def _is_admin(ix: discord.Interaction) -> bool:
    m = ix.guild.get_member(ix.user.id) if ix.guild else None
    return bool(m and (m.guild_permissions.administrator or m.guild_permissions.manage_guild))


# ── /balance ──────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="balance",
    description="Check your coin balance | เช็คยอดเงินของคุณ",
    guild=GUILD2_OBJ,
)
async def balance_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    gid = ix.guild_id
    uid = ix.user.id
    cfg    = load_config(gid)
    player = load_players(gid).get(str(uid), {})
    bal    = player.get("balance", 0)
    cur    = format_currency(bal, cfg)

    embed = discord.Embed(
        title=t(gid, "balance_title"),
        color=0xf1c40f,
    )
    embed.set_author(name=ix.user.display_name, icon_url=ix.user.display_avatar.url)
    embed.add_field(name=t(gid, "your_balance_label"), value=cur, inline=False)

    img = cfg.get("currency_image", "").strip()
    if img and img.startswith(("http://", "https://")):
        embed.set_thumbnail(url=img)

    view = _BalanceView(gid, uid)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class _BalanceView(discord.ui.View):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=120)
        self.gid = gid; self.uid = uid

    @discord.ui.button(label="Transfer", style=discord.ButtonStyle.primary, emoji="💸")
    async def btn_transfer(self, ix: discord.Interaction, _b):
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your balance.", ephemeral=True); return
        await ix.response.send_modal(_TransferModal(self.gid, self.uid))


class _TransferModal(discord.ui.Modal, title="Transfer Coins"):
    f_target = discord.ui.TextInput(label="Target User ID", max_length=30)
    f_amount = discord.ui.TextInput(label="Amount", max_length=20)
    f_note   = discord.ui.TextInput(label="Note (optional)", max_length=100, required=False)

    def __init__(self, gid: int, uid: int):
        super().__init__()
        self.gid = gid; self.uid = uid

    async def on_submit(self, ix: discord.Interaction):
        gid = self.gid
        cfg = load_config(gid)
        uid_str = str(self.uid)
        target_str = self.f_target.value.strip().lstrip("<@!>").rstrip(">")
        if not target_str.isdigit():
            await ix.response.send_message("Invalid user ID.", ephemeral=True); return
        target_id = int(target_str)
        if target_id == self.uid:
            await ix.response.send_message("Cannot transfer to yourself.", ephemeral=True); return
        try:
            amount = int(self.f_amount.value.strip())
        except ValueError:
            await ix.response.send_message("Invalid amount.", ephemeral=True); return
        if amount <= 0:
            await ix.response.send_message("Amount must be positive.", ephemeral=True); return

        players = load_players(gid)
        sender  = players.get(uid_str, {})
        if sender.get("balance", 0) < amount:
            await ix.response.send_message("Insufficient balance.", ephemeral=True); return
        target_player = players.get(str(target_id))
        if not target_player:
            await ix.response.send_message("Target player not registered.", ephemeral=True); return

        sender["balance"] = sender.get("balance", 0) - amount
        target_player["balance"] = target_player.get("balance", 0) + amount
        players[uid_str] = sender
        players[str(target_id)] = target_player
        save_players(gid, players)

        note = self.f_note.value.strip()
        cur  = format_currency(amount, cfg)
        embed = discord.Embed(
            title="Transfer Complete",
            description=f"Sent **{cur}** to <@{target_id}>",
            color=discord.Color.green(),
        )
        if note:
            embed.add_field(name="Note", value=note, inline=False)
        await ix.response.send_message(embed=embed, ephemeral=True)

        try:
            target_user = await bot.fetch_user(target_id)
            notify = discord.Embed(
                title="Coins Received",
                description=f"You received **{cur}** from <@{self.uid}>",
                color=discord.Color.gold(),
            )
            if note:
                notify.add_field(name="Note", value=note, inline=False)
            await target_user.send(embed=notify)
        except Exception:
            pass
        await log_event(bot, gid, "economy",
                        f"<@{self.uid}> transferred {amount} to <@{target_id}>{f' — {note}' if note else ''}")


# ── /transfer (alias / simpler flow via user mention) ────────────────────────

@bot.tree.command(
    name="transfer",
    description="Send coins to another player | โอนเงินให้ผู้เล่นอื่น",
    guild=GUILD2_OBJ,
)
@app_commands.describe(member="Player to send to", amount="Amount to send", note="Optional note")
async def transfer_cmd(ix: discord.Interaction, member: discord.Member, amount: int, note: str = ""):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    gid = ix.guild_id
    uid = ix.user.id
    if member.id == uid:
        await ix.response.send_message("Cannot transfer to yourself.", ephemeral=True); return
    if amount <= 0:
        await ix.response.send_message("Amount must be positive.", ephemeral=True); return

    cfg     = load_config(gid)
    players = load_players(gid)
    sender  = players.get(str(uid), {})
    if not sender:
        await ix.response.send_message("You have no character.", ephemeral=True); return
    if sender.get("balance", 0) < amount:
        await ix.response.send_message("Insufficient balance.", ephemeral=True); return
    target = players.get(str(member.id))
    if not target:
        await ix.response.send_message("Target player not registered.", ephemeral=True); return

    sender["balance"] = sender.get("balance", 0) - amount
    target["balance"] = target.get("balance", 0) + amount
    players[str(uid)] = sender
    players[str(member.id)] = target
    save_players(gid, players)

    cur = format_currency(amount, cfg)
    embed = discord.Embed(
        title="Transfer Complete",
        description=f"Sent **{cur}** to {member.mention}",
        color=discord.Color.green(),
    )
    if note:
        embed.add_field(name="Note", value=note[:100], inline=False)
    await ix.response.send_message(embed=embed, ephemeral=True)

    try:
        notify = discord.Embed(
            title="Coins Received",
            description=f"You received **{cur}** from {ix.user.mention}",
            color=discord.Color.gold(),
        )
        if note:
            notify.add_field(name="Note", value=note[:100], inline=False)
        await member.send(embed=notify)
    except Exception:
        pass
    await log_event(bot, gid, "economy",
                    f"<@{uid}> transferred {amount} to <@{member.id}>{f' — {note}' if note else ''}")


# ── /eco-admin ────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="eco-admin",
    description="[Admin] Manage player economy | จัดการเศรษฐกิจผู้เล่น",
    guild=GUILD2_OBJ,
)
async def eco_admin_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    if not _is_admin(ix):
        await ix.response.send_message("Admin only.", ephemeral=True); return
    embed = discord.Embed(
        title="Economy Admin",
        description="Grant or remove coins from players.",
        color=0xe67e22,
    )
    await ix.response.send_message(embed=embed, view=_EcoAdminView(ix.guild_id), ephemeral=True)


class _EcoAdminView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        m = ix.guild.get_member(ix.user.id) if ix.guild else None
        if not (m and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)):
            await ix.response.send_message("Admin only.", ephemeral=True); return False
        return True

    @discord.ui.button(label="Grant Coins", style=discord.ButtonStyle.success, emoji="➕")
    async def btn_grant(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_EcoGrantModal(self.gid, action="grant"))

    @discord.ui.button(label="Remove Coins", style=discord.ButtonStyle.danger, emoji="➖")
    async def btn_remove(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_EcoGrantModal(self.gid, action="remove"))

    @discord.ui.button(label="Check Balance", style=discord.ButtonStyle.secondary, emoji="👀", row=1)
    async def btn_check(self, ix: discord.Interaction, _b):
        await ix.response.send_modal(_EcoCheckModal(self.gid))


class _EcoGrantModal(discord.ui.Modal):
    f_target = discord.ui.TextInput(label="User ID", max_length=30)
    f_amount = discord.ui.TextInput(label="Amount", max_length=20)
    f_reason = discord.ui.TextInput(label="Reason (optional)", max_length=100, required=False)

    def __init__(self, gid: int, action: str):
        super().__init__(title=f"{'Grant' if action == 'grant' else 'Remove'} Coins")
        self.gid = gid; self.action = action

    async def on_submit(self, ix: discord.Interaction):
        gid = self.gid
        cfg = load_config(gid)
        target_str = self.f_target.value.strip().lstrip("<@!>").rstrip(">")
        if not target_str.isdigit():
            await ix.response.send_message("Invalid user ID.", ephemeral=True); return
        target_id = int(target_str)
        try:
            amount = int(self.f_amount.value.strip())
        except ValueError:
            await ix.response.send_message("Invalid amount.", ephemeral=True); return
        if amount <= 0:
            await ix.response.send_message("Amount must be positive.", ephemeral=True); return

        players = load_players(gid)
        player  = players.get(str(target_id))
        if not player:
            await ix.response.send_message("Player not found.", ephemeral=True); return

        if self.action == "grant":
            player["balance"] = player.get("balance", 0) + amount
            action_str = "granted to"
        else:
            new_bal = max(0, player.get("balance", 0) - amount)
            player["balance"] = new_bal
            action_str = "removed from"

        players[str(target_id)] = player
        save_players(gid, players)

        cur = format_currency(amount, cfg)
        reason = self.f_reason.value.strip()
        embed = discord.Embed(
            title=f"Economy Updated",
            description=f"**{cur}** {action_str} <@{target_id}>",
            color=discord.Color.green() if self.action == "grant" else discord.Color.red(),
        )
        embed.add_field(name="New Balance", value=format_currency(player["balance"], cfg), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        await ix.response.send_message(embed=embed, ephemeral=True)

        try:
            target_user = await bot.fetch_user(target_id)
            notify = discord.Embed(
                title=f"Balance {'Updated' if self.action == 'grant' else 'Adjusted'}",
                description=f"**{cur}** has been {'added to' if self.action == 'grant' else 'removed from'} your balance.",
                color=discord.Color.gold(),
            )
            if reason:
                notify.add_field(name="Reason", value=reason, inline=False)
            await target_user.send(embed=notify)
        except Exception:
            pass
        await log_event(bot, gid, "economy",
                        f"Admin {ix.user.display_name} {action_str} {amount} coins <@{target_id}>{f' — {reason}' if reason else ''}")


class _EcoCheckModal(discord.ui.Modal, title="Check Player Balance"):
    f_target = discord.ui.TextInput(label="User ID", max_length=30)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        gid = self.gid
        cfg = load_config(gid)
        target_str = self.f_target.value.strip().lstrip("<@!>").rstrip(">")
        if not target_str.isdigit():
            await ix.response.send_message("Invalid user ID.", ephemeral=True); return
        target_id = int(target_str)
        players = load_players(gid)
        player  = players.get(str(target_id), {})
        if not player:
            await ix.response.send_message("Player not found.", ephemeral=True); return
        bal = player.get("balance", 0)
        cur = format_currency(bal, cfg)
        embed = discord.Embed(
            title="Player Balance",
            description=f"<@{target_id}> — **{cur}**",
            color=0xf1c40f,
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
