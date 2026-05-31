"""XP & Level system — /xp command."""
import discord

from core.instance import bot
from core.shared import (
    t, load_players, _get_level, _xp_for_level, EMBED_COLOR,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _xp_bar(xp: int, level: int, width: int = 10) -> str:
    """Return a progress bar string like  ▓▓▓▓▓░░░░░ 540/900."""
    cur  = _xp_for_level(level)
    nxt  = _xp_for_level(level + 1)
    prog = xp - cur
    span = nxt - cur
    filled = min(width, int(prog / span * width)) if span > 0 else width
    bar = "▓" * filled + "░" * (width - filled)
    return f"{bar} {prog}/{span}"


def _build_xp_embed(uid: int, gid: int) -> discord.Embed:
    player = load_players(gid).get(str(uid), {})
    xp     = player.get("xp", 0)
    level  = _get_level(xp)
    bar    = _xp_bar(xp, level)
    nxt    = _xp_for_level(level + 1)

    embed = discord.Embed(
        title=t(gid, "xp_title"),
        color=EMBED_COLOR,
    )
    embed.add_field(name=t(gid, "level_label"), value=str(level), inline=True)
    embed.add_field(name=t(gid, "xp_label"),    value=str(xp),    inline=True)
    embed.add_field(
        name=t(gid, "xp_progress_label"),
        value=f"`{bar}`\n*{t(gid, 'next_level_label')} {nxt} XP*",
        inline=False,
    )
    return embed


# ── View ──────────────────────────────────────────────────────────────────────

class XPView(discord.ui.View):
    def __init__(self, uid: int, gid: int):
        super().__init__(timeout=300)
        self.uid = uid
        self.gid = gid

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.secondary)
    async def refresh_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        embed = _build_xp_embed(self.uid, self.gid)
        await ix.response.edit_message(embed=embed, view=self)

    @discord.ui.button(style=discord.ButtonStyle.danger)
    async def done_btn(self, ix: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=None)

    def _localise(self):
        """Apply localised labels; call once after construction."""
        self.done_btn.label = t(self.gid, "done_btn")


# ── Slash command ─────────────────────────────────────────────────────────────

@bot.tree.command(
    name="xp",
    description="View your XP and level",
    description_localizations={"th": "ดู XP และระดับของคุณ"},
)
async def xp_cmd(ix: discord.Interaction):
    gid  = ix.guild_id
    uid  = ix.user.id

    embed = _build_xp_embed(uid, gid)
    view  = XPView(uid, gid)
    view._localise()

    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
