"""Economy system — /balance command with transfer and admin tools."""
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    t, load_players, save_players, load_config,
    format_currency, EMBED_COLOR,
)


# ── Modals ────────────────────────────────────────────────────────────────────

class TransferAmountModal(discord.ui.Modal):
    """Modal that collects the transfer amount, then performs the transfer."""

    def __init__(self, gid: int, sender_id: int, target: discord.Member):
        super().__init__(title="Transfer")
        self.gid       = gid
        self.sender_id = sender_id
        self.target    = target

        self.amount_input = discord.ui.TextInput(
            label=t(gid, "transfer_amount_field"),
            placeholder="100",
            min_length=1,
            max_length=10,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, ix: discord.Interaction):
        gid = self.gid
        cfg = load_config(gid)

        try:
            amount = int(self.amount_input.value.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            embed = discord.Embed(
                description="❌ Invalid amount.",
                color=0xFF0000,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        players    = load_players(gid)
        sender_key = str(self.sender_id)
        target_key = str(self.target.id)

        sender_data = players.get(sender_key, {})
        sender_bal  = sender_data.get("balance", 0)

        if sender_bal < amount:
            embed = discord.Embed(
                description=t(gid, "transfer_insufficient"),
                color=0xFF0000,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        # Deduct from sender
        sender_data["balance"] = sender_bal - amount
        players[sender_key]    = sender_data

        # Credit to target
        target_data            = players.get(target_key, {})
        target_data["balance"] = target_data.get("balance", 0) + amount
        players[target_key]    = target_data

        save_players(gid, players)

        cur_str = format_currency(amount, cfg)

        # Notify sender
        embed = discord.Embed(
            description=t(
                gid, "transfer_success",
                amount=cur_str,
                currency=cfg.get("currency_name", "Coins"),
                target=self.target.display_name,
            ),
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, ephemeral=True)

        # DM the recipient
        try:
            dm_embed = discord.Embed(
                description=t(
                    gid, "transfer_received",
                    sender=ix.user.display_name,
                    amount=cur_str,
                    currency=cfg.get("currency_name", "Coins"),
                ),
                color=EMBED_COLOR,
            )
            await self.target.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass


class AdminGrantModal(discord.ui.Modal):
    """Admin modal to grant money to a player."""

    def __init__(self, gid: int, target: discord.Member, remove: bool = False):
        title = t(gid, "admin_remove_btn" if remove else "admin_grant_btn")[:45]
        super().__init__(title=title)
        self.gid    = gid
        self.target = target
        self.remove = remove

        self.amount_input = discord.ui.TextInput(
            label=t(gid, "admin_grant_amount_field"),
            placeholder="500",
            min_length=1,
            max_length=10,
        )
        self.add_item(self.amount_input)

    async def on_submit(self, ix: discord.Interaction):
        gid = self.gid
        cfg = load_config(gid)

        try:
            amount = int(self.amount_input.value.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            embed = discord.Embed(description="❌ Invalid amount.", color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        players    = load_players(gid)
        target_key = str(self.target.id)
        target_data = players.get(target_key, {})

        if self.remove:
            target_data["balance"] = max(0, target_data.get("balance", 0) - amount)
            msg_key = "admin_remove_success"
        else:
            target_data["balance"] = target_data.get("balance", 0) + amount
            msg_key = "admin_grant_success"

        players[target_key] = target_data
        save_players(gid, players)

        cur_str = format_currency(amount, cfg)
        embed = discord.Embed(
            description=t(
                gid, msg_key,
                amount=cur_str,
                currency=cfg.get("currency_name", "Coins"),
                target=self.target.display_name,
            ),
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, ephemeral=True)


# ── Views ─────────────────────────────────────────────────────────────────────

class TransferUserSelect(discord.ui.UserSelect):
    """Select a user to transfer money to."""

    def __init__(self, gid: int, sender_id: int):
        super().__init__(placeholder="Select recipient…", min_values=1, max_values=1)
        self.gid       = gid
        self.sender_id = sender_id

    async def callback(self, ix: discord.Interaction):
        target = self.values[0]
        if target.id == self.sender_id:
            embed = discord.Embed(description="❌ Cannot transfer to yourself.", color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        await ix.response.send_modal(
            TransferAmountModal(self.gid, self.sender_id, target)
        )


class AdminGrantUserSelect(discord.ui.UserSelect):
    """Admin: select a user to grant/remove money from."""

    def __init__(self, gid: int, remove: bool = False):
        super().__init__(placeholder="Select player…", min_values=1, max_values=1)
        self.gid    = gid
        self.remove = remove

    async def callback(self, ix: discord.Interaction):
        if not ix.user.guild_permissions.administrator:
            embed = discord.Embed(
                description=t(self.gid, "admin_only"), color=0xFF0000
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        target = self.values[0]
        await ix.response.send_modal(
            AdminGrantModal(self.gid, target, remove=self.remove)
        )


class TransferSelectView(discord.ui.View):
    """Ephemeral view with just the user-select for transfer."""

    def __init__(self, gid: int, sender_id: int):
        super().__init__(timeout=120)
        self.add_item(TransferUserSelect(gid, sender_id))


class AdminGrantSelectView(discord.ui.View):
    """Ephemeral view with just the user-select for admin grant/remove."""

    def __init__(self, gid: int, remove: bool = False):
        super().__init__(timeout=120)
        self.add_item(AdminGrantUserSelect(gid, remove=remove))


class BalanceView(discord.ui.View):
    """Main balance view shown on /balance."""

    def __init__(self, gid: int, uid: int, is_admin: bool):
        super().__init__(timeout=180)
        self.gid      = gid
        self.uid      = uid
        self.is_admin = is_admin

    # ── Transfer button ───────────────────────────────────────────────────────
    @discord.ui.button(label="💸 Transfer", style=discord.ButtonStyle.primary, row=0)
    async def transfer_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid
        # Override label with localised text
        button.label = t(gid, "transfer_btn")
        view = TransferSelectView(gid, ix.user.id)
        embed = discord.Embed(
            title=t(gid, "transfer_btn"),
            description="Select the player you want to send money to.",
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)

    # ── Admin: Grant ──────────────────────────────────────────────────────────
    @discord.ui.button(label="➕ Grant (Admin)", style=discord.ButtonStyle.success, row=1)
    async def admin_grant_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid
        if not ix.user.guild_permissions.administrator:
            embed = discord.Embed(description=t(gid, "admin_only"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        view  = AdminGrantSelectView(gid, remove=False)
        embed = discord.Embed(
            title=t(gid, "admin_grant_btn"),
            description="Select the player to grant money to.",
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)

    # ── Admin: Remove ─────────────────────────────────────────────────────────
    @discord.ui.button(label="➖ Remove (Admin)", style=discord.ButtonStyle.danger, row=1)
    async def admin_remove_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid
        if not ix.user.guild_permissions.administrator:
            embed = discord.Embed(description=t(gid, "admin_only"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        view  = AdminGrantSelectView(gid, remove=True)
        embed = discord.Embed(
            title=t(gid, "admin_remove_btn"),
            description="Select the player to remove money from.",
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── Slash command ─────────────────────────────────────────────────────────────

@bot.tree.command(
    name="balance",
    description="Check your coin balance",
    description_localizations={"th": "ดูยอดเงินของคุณ"},
)
async def balance_cmd(ix: discord.Interaction):
    gid    = ix.guild_id
    uid    = ix.user.id
    cfg    = load_config(gid)
    player = load_players(gid).get(str(uid), {})
    bal    = player.get("balance", 0)
    cur    = format_currency(bal, cfg)

    is_admin = ix.user.guild_permissions.administrator

    embed = discord.Embed(
        title=t(gid, "balance_title"),
        color=EMBED_COLOR,
    )
    embed.add_field(name=t(gid, "your_balance_label"), value=cur, inline=False)
    embed.set_footer(text=ix.user.display_name, icon_url=ix.user.display_avatar.url)

    img = cfg.get("currency_image", "").strip()
    if img and img.startswith(("http://", "https://")):
        embed.set_thumbnail(url=img)

    view = BalanceView(gid, uid, is_admin)

    # Remove admin buttons for non-admins so layout stays clean
    if not is_admin:
        view.remove_item(view.admin_grant_btn)
        view.remove_item(view.admin_remove_btn)

    # Localise the transfer button label immediately
    view.transfer_btn.label = t(gid, "transfer_btn")

    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
