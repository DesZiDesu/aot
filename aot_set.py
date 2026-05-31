"""Bot appearance commands — /set profile, /set banner (admin only)."""
import discord
from discord import app_commands
from discord.ui import LayoutView, Container, TextDisplay, Separator

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


def _reply(text: str) -> LayoutView:
    v = LayoutView(timeout=60)
    v.add_item(Container(TextDisplay(text)))
    return v


set_group = app_commands.Group(name="set", description="Change the bot's appearance (admin only)")


@set_group.command(name="profile", description="Change the bot's profile picture")
@_is_admin()
async def set_profile_cmd(ix: discord.Interaction, image: discord.Attachment):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    if image.content_type not in ALLOWED_TYPES:
        await ix.response.send_message(view=_reply("❌ Please upload a PNG, JPG, GIF, or WebP image."), ephemeral=True)
        return
    await ix.response.defer(ephemeral=True)
    try:
        data = await image.read()
        await bot.user.edit(avatar=data)
        await ix.followup.send(view=_reply("✅ Bot profile picture updated!"), ephemeral=True)
    except discord.HTTPException as e:
        await ix.followup.send(view=_reply(f"❌ Failed to update profile picture: {e}"), ephemeral=True)


@set_group.command(name="banner", description="Change the bot's banner")
@_is_admin()
async def set_banner_cmd(ix: discord.Interaction, image: discord.Attachment):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    if image.content_type not in ALLOWED_TYPES:
        await ix.response.send_message(view=_reply("❌ Please upload a PNG, JPG, GIF, or WebP image."), ephemeral=True)
        return
    await ix.response.defer(ephemeral=True)
    try:
        data = await image.read()
        await bot.user.edit(banner=data)
        await ix.followup.send(view=_reply("✅ Bot banner updated!"), ephemeral=True)
    except discord.HTTPException as e:
        await ix.followup.send(view=_reply(f"❌ Failed to update banner: {e}"), ephemeral=True)


@set_group.error
async def set_error(ix: discord.Interaction, error):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    if not ix.response.is_done():
        await ix.response.send_message(view=_reply("❌ Administrator only."), ephemeral=True)


bot.tree.add_command(set_group, guild=GUILD2_OBJ)