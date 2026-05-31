"""Backup & Restore — /backup command."""
import os
import io
import zipfile
import asyncio
import discord
from discord import app_commands

from core.instance import bot
from core.shared import t, DATA_DIR, log_event, EMBED_COLOR


# ── Admin check ───────────────────────────────────────────────────────────────

def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild:
            return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (
            m.guild_permissions.administrator or m.guild_permissions.manage_guild
        )
    return app_commands.check(pred)


# ── Main View ─────────────────────────────────────────────────────────────────

class BackupView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()

        create_btn = discord.ui.Button(
            label=t(self.gid, "backup_create_btn"),
            style=discord.ButtonStyle.green,
            emoji="📦",
            row=0,
        )
        restore_btn = discord.ui.Button(
            label=t(self.gid, "backup_restore_btn"),
            style=discord.ButtonStyle.secondary,
            emoji="🔄",
            row=0,
        )
        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            row=1,
        )

        create_btn.callback = self._create
        restore_btn.callback = self._restore
        done_btn.callback = self._done

        self.add_item(create_btn)
        self.add_item(restore_btn)
        self.add_item(done_btn)

    def _main_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title=t(self.gid, "backup_title"),
            description=(
                "Create a ZIP archive of all guild data files, "
                "or restore from a previously saved ZIP.\n\n"
                "**Create Backup** — packages all JSON data for this server.\n"
                "**Restore Backup** — upload a `.zip` file to overwrite saved data."
            ),
            color=EMBED_COLOR,
        )
        embed.set_footer(text="Only .json files belonging to this guild are included.")
        return embed

    async def _create(self, ix: discord.Interaction):
        await ix.response.defer(ephemeral=True)
        buf = io.BytesIO()
        file_count = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname in os.listdir(DATA_DIR):
                if fname.endswith(".json") and str(self.gid) in fname:
                    zf.write(DATA_DIR / fname, fname)
                    file_count += 1
        buf.seek(0)
        archive_name = f"backup_{self.gid}.zip"

        result_embed = discord.Embed(
            title="💾 " + t(self.gid, "backup_title"),
            description=t(self.gid, "backup_created_msg"),
            color=EMBED_COLOR,
        )
        result_embed.add_field(name="Files included", value=str(file_count), inline=True)
        result_embed.add_field(name="Archive", value=archive_name, inline=True)

        await ix.followup.send(
            embed=result_embed,
            file=discord.File(buf, filename=archive_name),
            ephemeral=True,
        )
        await log_event(
            bot, self.gid, "admin",
            f"{ix.user.display_name} created a data backup ({file_count} files)",
        )

    async def _restore(self, ix: discord.Interaction):
        prompt_embed = discord.Embed(
            title="🔄 " + t(self.gid, "backup_restore_btn"),
            description=t(self.gid, "backup_upload_prompt"),
            color=EMBED_COLOR,
        )
        prompt_embed.set_footer(text="Waiting for file upload… (60 s)")

        prompt_view = discord.ui.View(timeout=60)
        cancel_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"),
            style=discord.ButtonStyle.secondary,
        )

        async def _cancel(cancel_ix: discord.Interaction):
            self._build()
            await cancel_ix.response.edit_message(embed=self._main_embed(), view=self)

        cancel_btn.callback = _cancel
        prompt_view.add_item(cancel_btn)

        await ix.response.edit_message(embed=prompt_embed, view=prompt_view)

        def check(m: discord.Message) -> bool:
            return (
                m.author.id == ix.user.id
                and m.channel.id == ix.channel_id
                and bool(m.attachments)
            )

        try:
            msg = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            self._build()
            await ix.edit_original_response(embed=self._main_embed(), view=self)
            return

        attachment = msg.attachments[0]
        if not attachment.filename.endswith(".zip"):
            err_embed = discord.Embed(
                description=t(self.gid, "backup_invalid_file"),
                color=discord.Color.red(),
            )
            await ix.followup.send(embed=err_embed, ephemeral=True)
            self._build()
            await ix.edit_original_response(embed=self._main_embed(), view=self)
            return

        raw = await attachment.read()
        buf = io.BytesIO(raw)
        restored = 0
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                for name in zf.namelist():
                    if str(self.gid) in name and name.endswith(".json"):
                        zf.extract(name, DATA_DIR)
                        restored += 1
        except Exception as exc:
            err_embed = discord.Embed(
                title="Restore Failed",
                description=f"```{exc}```",
                color=discord.Color.red(),
            )
            await ix.followup.send(embed=err_embed, ephemeral=True)
            self._build()
            await ix.edit_original_response(embed=self._main_embed(), view=self)
            return

        try:
            await msg.delete()
        except Exception:
            pass

        ok_embed = discord.Embed(
            title="💾 " + t(self.gid, "backup_title"),
            description=t(self.gid, "backup_restored_msg"),
            color=EMBED_COLOR,
        )
        ok_embed.add_field(name="Files restored", value=str(restored), inline=True)
        await ix.followup.send(embed=ok_embed, ephemeral=True)
        await log_event(
            bot, self.gid, "admin",
            f"{ix.user.display_name} restored guild data from backup ({restored} files)",
        )
        self._build()
        await ix.edit_original_response(embed=self._main_embed(), view=self)

    async def _done(self, ix: discord.Interaction):
        closed_embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*",
            color=EMBED_COLOR,
        )
        self.clear_items()
        await ix.response.edit_message(embed=closed_embed, view=self)


# ── Slash command ─────────────────────────────────────────────────────────────

@bot.tree.command(
    name="backup",
    description="Create or restore a guild data backup",
    description_localizations={"th": "สำรองหรือกู้คืนข้อมูลของเซิร์ฟเวอร์"},
)
@_is_admin()
async def backup_cmd(ix: discord.Interaction):
    view = BackupView(ix.guild_id)
    embed = discord.Embed(
        title=t(ix.guild_id, "backup_title"),
        description=(
            "Create a ZIP archive of all guild data files, "
            "or restore from a previously saved ZIP.\n\n"
            "**Create Backup** — packages all JSON data for this server.\n"
            "**Restore Backup** — upload a `.zip` file to overwrite saved data."
        ),
        color=EMBED_COLOR,
    )
    embed.set_footer(text="Only .json files belonging to this guild are included.")
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


@backup_cmd.error
async def backup_error(ix: discord.Interaction, error):
    await ix.response.send_message(
        t(ix.guild_id, "admin_only"), ephemeral=True
    )
