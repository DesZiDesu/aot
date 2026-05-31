"""XP & Level system — /xp command, add_xp helper."""
import discord
from discord.ui import (LayoutView, Container, TextDisplay, Separator, ActionRow, Button)

from aot_bot_instance import bot
from aot_shared import t, load_players, _xp_for_level, _get_level


def _xp_bar(xp: int, level: int) -> str:
    cur  = _xp_for_level(level)
    nxt  = _xp_for_level(level + 1)
    prog = xp - cur
    span = nxt - cur
    pct  = min(10, int(prog / span * 10)) if span > 0 else 10
    return f"{'▓'*pct}{'░'*(10-pct)} {prog}/{span}"


class XPView(LayoutView):
    def __init__(self, uid: int, gid: int):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        player = load_players(self.gid).get(str(self.uid), {})
        xp     = player.get("xp", 0)
        level  = _get_level(xp)
        bar    = _xp_bar(xp, level)
        nxt    = _xp_for_level(level + 1)

        lines = [
            f"**{t(self.gid,'xp_title')}**",
            "",
            f"**{t(self.gid,'level_label')}:** {level}",
            f"**{t(self.gid,'xp_label')}:** {xp}",
            "",
            f"**{t(self.gid,'xp_progress_label')}:**",
            f"{bar}",
            f"*{t(self.gid,'next_level_label')} {nxt} XP*",
        ]

        refresh_btn = Button(label="🔄 Refresh", style=discord.ButtonStyle.secondary, custom_id="xp_ref")
        done_btn    = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="xp_done")
        refresh_btn.callback = self._refresh
        done_btn.callback    = self._done

        self.add_item(Container(
            TextDisplay("\n".join(lines)), Separator(),
            ActionRow(refresh_btn, done_btn),
        ))

    async def _refresh(self, ix):
        self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


@bot.tree.command(name="xp",
                  description="View your XP and level",
                  description_localizations={"th": "ดู XP และระดับของคุณ"})
async def xp_cmd(ix: discord.Interaction):
    await ix.response.send_message(view=XPView(ix.user.id, ix.guild_id), ephemeral=True)
