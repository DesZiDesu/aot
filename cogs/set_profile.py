"""Set profile / banner commands — /set profile, /set banner."""
import discord
from discord import app_commands
from discord.ext import commands

from core.instance import bot
from core.shared import (
    t,
    load_players, save_players,
    load_config,
    assign_roles,
    log_event,
    EMBED_COLOR,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _not_registered_embed(gid: int) -> discord.Embed:
    return discord.Embed(
        description=t(gid, "not_registered"),
        color=EMBED_COLOR,
    )


# ── Modals ────────────────────────────────────────────────────────────────────

class ProfileModal(discord.ui.Modal, title="Edit Character Profile"):
    f_name       = discord.ui.TextInput(label="Character Name",          max_length=80)
    f_age        = discord.ui.TextInput(label="Age",                     max_length=20)
    f_gender     = discord.ui.TextInput(label="Gender",                  max_length=40)
    f_appearance = discord.ui.TextInput(
        label="Appearance",
        max_length=500,
        style=discord.TextStyle.paragraph,
        required=False,
    )
    f_image      = discord.ui.TextInput(
        label="Profile Image URL (optional)",
        max_length=300,
        required=False,
    )

    def __init__(self, gid: int, uid: int, player: dict):
        super().__init__()
        self.gid    = gid
        self.uid    = uid
        self.player = player

        # Pre-fill with existing data
        self.f_name.default       = player.get("name",       "")
        self.f_age.default        = player.get("age",        "")
        self.f_gender.default     = player.get("gender",     "")
        self.f_appearance.default = player.get("appearance", "")
        self.f_image.default      = player.get("image",      "")

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})

        player["name"]       = self.f_name.value.strip()
        player["age"]        = self.f_age.value.strip()
        player["gender"]     = self.f_gender.value.strip()
        player["appearance"] = (self.f_appearance.value or "").strip()

        img = (self.f_image.value or "").strip()
        if img:
            player["image"] = img

        players[str(self.uid)] = player
        save_players(self.gid, players)

        # Assign roles based on current faction/rank/bloodline/shifter
        cfg    = load_config(self.gid)
        member = ix.guild.get_member(self.uid) if ix.guild else None
        if member:
            try:
                await assign_roles(member, player, cfg)
            except Exception:
                pass

        # Log the event
        display = ix.user.display_name
        await log_event(
            bot,
            self.gid,
            "profile",
            t(self.gid, "updated_msg", name=display, char=player.get("name", "?")),
        )

        embed = discord.Embed(
            title=t(self.gid, "profile_title"),
            description=t(self.gid, "updated_msg", name=display, char=player.get("name", "?")),
            color=EMBED_COLOR,
        )
        embed.add_field(name=t(self.gid, "name_label"),       value=player.get("name",       "?"), inline=True)
        embed.add_field(name=t(self.gid, "age_label"),         value=player.get("age",         "?"), inline=True)
        embed.add_field(name=t(self.gid, "gender_label"),      value=player.get("gender",      "?"), inline=True)
        embed.add_field(name=t(self.gid, "appearance_label"),  value=player.get("appearance",  "?") or "—", inline=False)

        char_img = player.get("image", "").strip()
        if char_img and char_img.startswith(("http://", "https://")):
            embed.set_thumbnail(url=char_img)

        await ix.response.send_message(embed=embed, ephemeral=True)


class BannerModal(discord.ui.Modal, title="Set Profile Banner"):
    f_url = discord.ui.TextInput(
        label="Banner Image URL",
        max_length=300,
        placeholder="https://...",
    )

    def __init__(self, gid: int, uid: int, player: dict):
        super().__init__()
        self.gid    = gid
        self.uid    = uid
        self.player = player
        self.f_url.default = player.get("banner", "")

    async def on_submit(self, ix: discord.Interaction):
        url = (self.f_url.value or "").strip()

        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["banner"] = url
        players[str(self.uid)] = player
        save_players(self.gid, players)

        display = ix.user.display_name
        await log_event(
            bot,
            self.gid,
            "profile",
            f"{display} updated their banner.",
        )

        embed = discord.Embed(
            description="✅ Banner updated!",
            color=EMBED_COLOR,
        )
        if url.startswith(("http://", "https://")):
            embed.set_image(url=url)

        await ix.response.send_message(embed=embed, ephemeral=True)


# ── Command group ─────────────────────────────────────────────────────────────

set_group = app_commands.Group(
    name="set",
    description="Update your character information",
    description_localizations={"th": "อัปเดตข้อมูลตัวละครของคุณ"},
)


@set_group.command(
    name="profile",
    description="Edit your character profile (name, age, gender, appearance, image)",
    description_localizations={"th": "แก้ไขโปรไฟล์ตัวละคร (ชื่อ, อายุ, เพศ, รูปลักษณ์, รูปภาพ)"},
)
async def set_profile_cmd(ix: discord.Interaction):
    gid     = ix.guild_id
    players = load_players(gid)
    player  = players.get(str(ix.user.id))

    if not player:
        await ix.response.send_message(embed=_not_registered_embed(gid), ephemeral=True)
        return

    await ix.response.send_modal(ProfileModal(gid, ix.user.id, player))


@set_group.command(
    name="banner",
    description="Set your character's banner image URL",
    description_localizations={"th": "ตั้งค่า URL รูปภาพแบนเนอร์ของตัวละคร"},
)
async def set_banner_cmd(ix: discord.Interaction):
    gid     = ix.guild_id
    players = load_players(gid)
    player  = players.get(str(ix.user.id))

    if not player:
        await ix.response.send_message(embed=_not_registered_embed(gid), ephemeral=True)
        return

    await ix.response.send_modal(BannerModal(gid, ix.user.id, player))


bot.tree.add_command(set_group)


# ── Cog loader ────────────────────────────────────────────────────────────────

class SetProfileCog(commands.Cog):
    pass


async def setup(b: commands.Bot):
    await b.add_cog(SetProfileCog(b))
