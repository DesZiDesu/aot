"""Backup & Restore — /backup command."""
import os, io, zipfile, asyncio
import discord
from discord import app_commands
from discord.ui import (LayoutView, Container, TextDisplay, Separator, ActionRow, Button)

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import t, DATA_DIR, log_event


def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


class BackupView(LayoutView):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        text = f"**{t(self.gid,'backup_title')}**\n\nCreate a ZIP of all guild data, or restore from a previously saved ZIP."
        create_btn  = Button(label=t(self.gid, "backup_create_btn"),
                             style=discord.ButtonStyle.green, custom_id="bk_create")
        restore_btn = Button(label=t(self.gid, "backup_restore_btn"),
                             style=discord.ButtonStyle.secondary, custom_id="bk_restore")
        done_btn    = Button(label=t(self.gid, "done_btn"),
                             style=discord.ButtonStyle.danger, custom_id="bk_done")
        create_btn.callback  = self._create
        restore_btn.callback = self._restore
        done_btn.callback    = self._done
        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(create_btn, restore_btn),
            ActionRow(done_btn),
        ))

    async def _create(self, ix: discord.Interaction):
        await ix.response.defer(ephemeral=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(DATA_DIR):
                if fname.endswith(".json") and str(self.gid) in fname:
                    zf.write(DATA_DIR / fname, fname)
        buf.seek(0)
        fname = f"backup_{self.gid}.zip"
        await ix.followup.send(
            t(self.gid, "backup_created_msg"),
            file=discord.File(buf, filename=fname),
            ephemeral=True,
        )
        await log_event(bot, self.gid, "admin",
                        f"{ix.user.display_name} created a data backup")

    async def _restore(self, ix: discord.Interaction):
        prompt_view = LayoutView(timeout=60)
        prompt_view.add_item(Container(TextDisplay(t(self.gid, "backup_upload_prompt"))))
        await ix.response.edit_message(view=prompt_view)

        def check(m: discord.Message):
            return (m.author.id == ix.user.id
                    and m.channel.id == ix.channel_id
                    and m.attachments)

        try:
            msg = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            self._build(); await ix.edit_original_response(view=self); return

        attachment = msg.attachments[0]
        if not attachment.filename.endswith(".zip"):
            await ix.followup.send(t(self.gid, "backup_invalid_file"), ephemeral=True)
            self._build(); await ix.edit_original_response(view=self); return

        data = await attachment.read()
        buf  = io.BytesIO(data)
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                for name in zf.namelist():
                    if str(self.gid) in name and name.endswith(".json"):
                        zf.extract(name, DATA_DIR)
        except Exception as e:
            await ix.followup.send(f"Restore failed: {e}", ephemeral=True)
            self._build(); await ix.edit_original_response(view=self); return

        try:
            await msg.delete()
        except Exception:
            pass
        await ix.followup.send(t(self.gid, "backup_restored_msg"), ephemeral=True)
        await log_event(bot, self.gid, "admin",
                        f"{ix.user.display_name} restored guild data from backup")
        self._build(); await ix.edit_original_response(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


@bot.tree.command(name="backup",
                  description="Create or restore a data backup",
                  guild=GUILD2_OBJ)
@_is_admin()
async def backup_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    await ix.response.send_message(view=BackupView(ix.guild_id), ephemeral=True)

@backup_cmd.error
async def backup_error(ix, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
