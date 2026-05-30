"""Economy system — /balance command."""
import discord
from aot_bot_instance import bot
from aot_shared import t, load_players, load_config, format_currency
from discord.ui import LayoutView, Container, TextDisplay, Separator, ActionRow


@bot.tree.command(name="balance", description="Check your coin balance")
async def balance_cmd(ix: discord.Interaction):
    gid = ix.guild_id; uid = ix.user.id
    cfg    = load_config(gid)
    player = load_players(gid).get(str(uid), {})
    bal    = player.get("balance", 0)
    cur    = format_currency(bal, cfg)

    img = cfg.get("currency_image", "").strip()
    lines = [
        f"**{t(gid,'balance_title')}**",
        "",
        f"**{t(gid,'your_balance_label')}:** {cur}",
    ]

    v = LayoutView(timeout=60)
    from discord.ui import MediaGallery
    from discord.components import MediaGalleryItem
    children = [TextDisplay("\n".join(lines))]
    if img and img.startswith(("http://", "https://")):
        children.append(Separator())
        children.append(MediaGallery(MediaGalleryItem(media=img)))
    v.add_item(Container(*children))
    await ix.response.send_message(view=v, ephemeral=True)
