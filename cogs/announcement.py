"""Announcement system — /paradis-announcement (Embed UI)."""
import time, uuid
import discord
from discord import app_commands
from discord.ext import commands

from core.instance import bot
from core.shared import (
    t, load_config, load_announcements, save_announcements,
    EMBED_COLOR,
)


# ── Permission check ──────────────────────────────────────────────────────────

def _can_announce(ix: discord.Interaction) -> bool:
    if not ix.guild:
        return False
    m = ix.guild.get_member(ix.user.id)
    if not m:
        return False
    if m.guild_permissions.administrator or m.guild_permissions.manage_guild:
        return True
    cfg = load_config(ix.guild_id)
    permitted = cfg.get("announcement_permitted_roles", [])
    return any(str(r.id) in permitted for r in m.roles)


# ── Modals ────────────────────────────────────────────────────────────────────

class NewDraftModal(discord.ui.Modal, title="New Announcement"):
    f_name = discord.ui.TextInput(label="Announcement Name", max_length=80)

    def __init__(self, gid: int, parent: "AnnouncementListView"):
        super().__init__()
        self.gid    = gid
        self.parent = parent
        self.f_name.label = t(gid, "draft_name_field")

    async def on_submit(self, ix: discord.Interaction):
        name = self.f_name.value.strip()
        if not name:
            await ix.response.defer()
            return
        db = load_announcements(self.gid)
        draft_id = str(uuid.uuid4())[:8]
        db["drafts"][draft_id] = {
            "name":       name,
            "title":      name,
            "content":    "",
            "author_id":  str(ix.user.id),
            "created_at": time.time(),
        }
        save_announcements(self.gid, db)
        self.parent._build()
        embed = _list_embed(self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)


class EditTitleModal(discord.ui.Modal, title="Edit Title"):
    f_title = discord.ui.TextInput(label="Title", max_length=100)

    def __init__(self, gid: int, draft_id: str, parent: "DraftDetailView"):
        super().__init__()
        self.gid      = gid
        self.draft_id = draft_id
        self.parent   = parent
        self.f_title.label = t(gid, "ann_title_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_announcements(self.gid)
        if self.draft_id in db["drafts"]:
            db["drafts"][self.draft_id]["title"] = self.f_title.value.strip()
            save_announcements(self.gid, db)
        self.parent._build()
        embed = _draft_embed(self.gid, self.draft_id)
        await ix.response.edit_message(embed=embed, view=self.parent)


class EditContentModal(discord.ui.Modal, title="Edit Content"):
    f_content = discord.ui.TextInput(
        label="Content",
        style=discord.TextStyle.paragraph,
        max_length=2000,
    )

    def __init__(self, gid: int, draft_id: str, parent: "DraftDetailView"):
        super().__init__()
        self.gid      = gid
        self.draft_id = draft_id
        self.parent   = parent
        self.f_content.label = t(gid, "ann_content_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_announcements(self.gid)
        if self.draft_id in db["drafts"]:
            db["drafts"][self.draft_id]["content"] = self.f_content.value.strip()
            save_announcements(self.gid, db)
        self.parent._build()
        embed = _draft_embed(self.gid, self.draft_id)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Embed builders ────────────────────────────────────────────────────────────

def _list_embed(gid: int) -> discord.Embed:
    db     = load_announcements(gid)
    drafts = db.get("drafts", {})
    embed  = discord.Embed(
        title=t(gid, "announcement_title"),
        color=EMBED_COLOR,
    )
    if drafts:
        lines = [
            f"• **{d['name']}** — `{did}`"
            for did, d in list(drafts.items())[:10]
        ]
        embed.description = "\n".join(lines)
    else:
        embed.description = t(gid, "no_drafts")
    return embed


def _draft_embed(gid: int, draft_id: str) -> discord.Embed:
    db    = load_announcements(gid)
    draft = db.get("drafts", {}).get(draft_id)
    if not draft:
        return discord.Embed(
            description="Draft not found.",
            color=EMBED_COLOR,
        )
    content = draft.get("content", "") or "*(no content)*"
    embed = discord.Embed(
        title=f"📢 {draft['name']}",
        color=EMBED_COLOR,
    )
    embed.add_field(
        name=t(gid, "ann_title_field"),
        value=draft.get("title", "*(no title)*"),
        inline=False,
    )
    embed.add_field(
        name=t(gid, "ann_content_field"),
        value=content[:1000] + ("…" if len(content) > 1000 else ""),
        inline=False,
    )
    return embed


# ── Draft Detail View ─────────────────────────────────────────────────────────

class DraftDetailView(discord.ui.View):
    def __init__(self, gid: int, draft_id: str, parent: "AnnouncementListView"):
        super().__init__(timeout=300)
        self.gid      = gid
        self.draft_id = draft_id
        self.parent   = parent
        self._build()

    def _build(self):
        self.clear_items()

        et_btn = discord.ui.Button(
            label=t(self.gid, "edit_title_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="dd_et",
            row=0,
        )
        ec_btn = discord.ui.Button(
            label=t(self.gid, "edit_content_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="dd_ec",
            row=0,
        )
        pub_btn = discord.ui.Button(
            label=t(self.gid, "publish_btn"),
            style=discord.ButtonStyle.green,
            custom_id="dd_pub",
            row=1,
        )
        del_btn = discord.ui.Button(
            label=t(self.gid, "delete_draft_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="dd_del",
            row=2,
        )
        bk_btn = discord.ui.Button(
            label=t(self.gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="dd_bk",
            row=2,
        )

        et_btn.callback  = self._edit_title
        ec_btn.callback  = self._edit_content
        pub_btn.callback = self._publish
        del_btn.callback = self._delete
        bk_btn.callback  = self._back

        for item in (et_btn, ec_btn, pub_btn, del_btn, bk_btn):
            self.add_item(item)

    async def _edit_title(self, ix: discord.Interaction):
        db    = load_announcements(self.gid)
        draft = db.get("drafts", {}).get(self.draft_id, {})
        m = EditTitleModal(self.gid, self.draft_id, self)
        m.f_title.default = draft.get("title", "")
        await ix.response.send_modal(m)

    async def _edit_content(self, ix: discord.Interaction):
        db    = load_announcements(self.gid)
        draft = db.get("drafts", {}).get(self.draft_id, {})
        m = EditContentModal(self.gid, self.draft_id, self)
        m.f_content.default = draft.get("content", "")
        await ix.response.send_modal(m)

    async def _publish(self, ix: discord.Interaction):
        cfg      = load_config(self.gid)
        channels = cfg.get("announcement_channels", [])
        if not channels:
            await ix.response.send_message(
                t(self.gid, "no_ann_channels"), ephemeral=True
            )
            return

        db    = load_announcements(self.gid)
        draft = db.get("drafts", {}).get(self.draft_id, {})
        title   = draft.get("title",   "Announcement")
        content = draft.get("content", "")

        # Build the published announcement as a rich Embed
        ann_embed = discord.Embed(
            title=title,
            description=content,
            color=EMBED_COLOR,
        )
        if ix.guild:
            ann_embed.set_footer(text=ix.guild.name)

        sent = 0
        for ch_id in channels:
            # CRITICAL FIX: Support ALL channel types (text, voice text, thread,
            # forum post, news channel, etc.) by using get_channel / fetch_channel
            # and catching send errors gracefully.
            ch = ix.guild.get_channel(int(ch_id))
            if ch is None:
                try:
                    ch = await ix.guild.fetch_channel(int(ch_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    ch = None
            if ch is not None:
                try:
                    await ch.send(embed=ann_embed)
                    sent += 1
                except (discord.Forbidden, discord.HTTPException):
                    pass

        await ix.response.send_message(
            f"✅ {t(self.gid, 'ann_published')} Sent to {sent} channel(s).",
            ephemeral=True,
        )

    async def _delete(self, ix: discord.Interaction):
        db = load_announcements(self.gid)
        db["drafts"].pop(self.draft_id, None)
        save_announcements(self.gid, db)
        self.parent._build()
        embed = _list_embed(self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._build()
        embed = _list_embed(self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Draft List View ───────────────────────────────────────────────────────────

class AnnouncementListView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        db     = load_announcements(self.gid)
        drafts = db.get("drafts", {})

        create_btn = discord.ui.Button(
            label=t(self.gid, "create_draft_btn"),
            style=discord.ButtonStyle.green,
            custom_id="al_create",
            row=0,
        )
        create_btn.callback = self._create
        self.add_item(create_btn)

        if drafts:
            opts = [
                discord.SelectOption(label=d["name"][:100], value=did)
                for did, d in list(drafts.items())[:25]
            ]
            sel = discord.ui.Select(
                placeholder="Open draft…",
                options=opts,
                custom_id="al_sel",
                row=1,
            )
            sel.callback = self._open
            self.add_item(sel)

    async def _create(self, ix: discord.Interaction):
        await ix.response.send_modal(NewDraftModal(self.gid, self))

    async def _open(self, ix: discord.Interaction):
        did  = ix.data["values"][0]
        view = DraftDetailView(self.gid, did, self)
        embed = _draft_embed(self.gid, did)
        await ix.response.edit_message(embed=embed, view=view)


# ── Cog & Command ─────────────────────────────────────────────────────────────

class AnnouncementCog(commands.Cog):
    def __init__(self, bot_instance: commands.Bot):
        self.bot = bot_instance

    @app_commands.command(
        name="paradis-announcement",
        description="Create and publish announcements",
        description_localizations={"th": "สร้างและเผยแพร่ประกาศ"},
    )
    async def announcement_cmd(self, ix: discord.Interaction):
        if not _can_announce(ix):
            embed = discord.Embed(
                description=t(ix.guild_id, "ann_no_permission"),
                color=EMBED_COLOR,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        view  = AnnouncementListView(ix.guild_id)
        embed = _list_embed(ix.guild_id)
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot_instance: commands.Bot):
    await bot_instance.add_cog(AnnouncementCog(bot_instance))
