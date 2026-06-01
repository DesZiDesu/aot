"""Announcement system — /paradis-announcement with full embed UI and all channel type support."""
import time, uuid
import discord

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_config, load_announcements, save_announcements,
)


def _can_announce(ix: discord.Interaction) -> bool:
    if not ix.guild: return False
    m = ix.guild.get_member(ix.user.id)
    if not m: return False
    if m.guild_permissions.administrator or m.guild_permissions.manage_guild:
        return True
    cfg = load_config(ix.guild_id)
    permitted = cfg.get("announcement_permitted_roles", [])
    return any(str(r.id) in permitted for r in m.roles)


def _draft_embed(draft: dict, gid: int) -> discord.Embed:
    title   = draft.get("title", "*(no title)*")
    content = draft.get("content", "") or "*(no content)*"
    embed = discord.Embed(
        title=f"Draft: {draft.get('name', '?')}",
        color=0x3498db,
    )
    embed.add_field(name="Title", value=title[:1024], inline=False)
    embed.add_field(name="Content Preview", value=content[:512] + ("…" if len(content) > 512 else ""), inline=False)
    return embed


def _list_embed(gid: int) -> discord.Embed:
    db     = load_announcements(gid)
    drafts = db.get("drafts", {})
    embed  = discord.Embed(
        title=t(gid, "announcement_title"),
        description=t(gid, "no_drafts") if not drafts else "\n".join(
            f"• **{d['name']}** — `{did}`" for did, d in list(drafts.items())[:15]
        ),
        color=0x3498db,
    )
    return embed


# ── Modals ────────────────────────────────────────────────────────────────────

class NewDraftModal(discord.ui.Modal, title="New Announcement"):
    f_name = discord.ui.TextInput(label="Announcement Name", max_length=80)

    def __init__(self, gid: int, parent):
        super().__init__()
        self.gid = gid; self.parent = parent
        self.f_name.label = t(gid, "draft_name_field")

    async def on_submit(self, ix: discord.Interaction):
        name = self.f_name.value.strip()
        if not name:
            await ix.response.defer(); return
        db = load_announcements(self.gid)
        did = str(uuid.uuid4())[:8]
        db["drafts"][did] = {
            "name": name, "title": name, "content": "",
            "author_id": str(ix.user.id), "created_at": time.time(),
        }
        save_announcements(self.gid, db)
        self.parent._rebuild()
        await ix.response.edit_message(embed=_list_embed(self.gid), view=self.parent)


class EditTitleModal(discord.ui.Modal, title="Edit Title"):
    f_title = discord.ui.TextInput(label="Title", max_length=100)

    def __init__(self, gid: int, draft_id: str, parent):
        super().__init__()
        self.gid = gid; self.draft_id = draft_id; self.parent = parent
        self.f_title.label = t(gid, "ann_title_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_announcements(self.gid)
        if self.draft_id in db["drafts"]:
            db["drafts"][self.draft_id]["title"] = self.f_title.value.strip()
            save_announcements(self.gid, db)
        draft = db["drafts"].get(self.draft_id, {})
        await ix.response.edit_message(embed=_draft_embed(draft, self.gid), view=self.parent)


class EditContentModal(discord.ui.Modal, title="Edit Content"):
    f_content = discord.ui.TextInput(label="Content", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, gid: int, draft_id: str, parent):
        super().__init__()
        self.gid = gid; self.draft_id = draft_id; self.parent = parent
        self.f_content.label = t(gid, "ann_content_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_announcements(self.gid)
        if self.draft_id in db["drafts"]:
            db["drafts"][self.draft_id]["content"] = self.f_content.value.strip()
            save_announcements(self.gid, db)
        draft = db["drafts"].get(self.draft_id, {})
        await ix.response.edit_message(embed=_draft_embed(draft, self.gid), view=self.parent)


# ── Draft detail view ─────────────────────────────────────────────────────────

class DraftDetailView(discord.ui.View):
    def __init__(self, gid: int, draft_id: str, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.draft_id = draft_id; self.parent = parent
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        btn_title   = discord.ui.Button(label=t(self.gid,"edit_title_btn"),   style=discord.ButtonStyle.secondary, row=0)
        btn_content = discord.ui.Button(label=t(self.gid,"edit_content_btn"), style=discord.ButtonStyle.secondary, row=0)
        btn_pub     = discord.ui.Button(label=t(self.gid,"publish_btn"),      style=discord.ButtonStyle.success,   row=1)
        btn_del     = discord.ui.Button(label=t(self.gid,"delete_draft_btn"), style=discord.ButtonStyle.danger,    row=1)
        btn_bk      = discord.ui.Button(label=t(self.gid,"back_btn"),         style=discord.ButtonStyle.secondary, row=1)

        btn_title.callback   = self._edit_title
        btn_content.callback = self._edit_content
        btn_pub.callback     = self._publish
        btn_del.callback     = self._delete
        btn_bk.callback      = self._back

        self.add_item(btn_title)
        self.add_item(btn_content)
        self.add_item(btn_pub)
        self.add_item(btn_del)
        self.add_item(btn_bk)

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
        cfg = load_config(self.gid)
        channels = cfg.get("announcement_channels", [])
        if not channels:
            await ix.response.send_message(t(self.gid, "no_ann_channels"), ephemeral=True); return

        db    = load_announcements(self.gid)
        draft = db.get("drafts", {}).get(self.draft_id, {})
        title   = draft.get("title",   "Announcement")
        content = draft.get("content", "")

        embed = discord.Embed(title=f"📢 {title}", description=content, color=0x2ecc71)
        embed.set_footer(text=f"By {ix.user.display_name}")

        sent = 0
        for cid in channels:
            try:
                ch = ix.guild.get_channel(int(cid))
                if ch is None:
                    continue
                # Support text channels, news channels, threads, forum threads
                if isinstance(ch, (discord.TextChannel, discord.NewsChannel,
                                   discord.Thread, discord.VoiceChannel,
                                   discord.StageChannel)):
                    await ch.send(embed=embed)
                    sent += 1
                elif isinstance(ch, discord.ForumChannel):
                    # Create a new post in the forum
                    await ch.create_thread(name=title[:100], embed=embed)
                    sent += 1
            except Exception:
                pass

        await ix.response.send_message(
            f"✅ {t(self.gid, 'ann_published')} — Sent to {sent} channel(s).",
            ephemeral=True,
        )

    async def _delete(self, ix: discord.Interaction):
        db = load_announcements(self.gid)
        db["drafts"].pop(self.draft_id, None)
        save_announcements(self.gid, db)
        self.parent._rebuild()
        await ix.response.edit_message(embed=_list_embed(self.gid), view=self.parent)

    async def _back(self, ix: discord.Interaction):
        self.parent._rebuild()
        await ix.response.edit_message(embed=_list_embed(self.gid), view=self.parent)


# ── Draft list view ───────────────────────────────────────────────────────────

class AnnouncementListView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        db     = load_announcements(self.gid)
        drafts = db.get("drafts", {})

        btn_create = discord.ui.Button(
            label=t(self.gid, "create_draft_btn"),
            style=discord.ButtonStyle.success,
            row=0,
        )
        btn_create.callback = self._create
        self.add_item(btn_create)

        if drafts:
            opts = [
                discord.SelectOption(label=d["name"][:100], value=did)
                for did, d in list(drafts.items())[:25]
            ]
            sel = discord.ui.Select(placeholder="Open draft…", options=opts, row=1)
            sel.callback = self._open
            self.add_item(sel)

    async def _create(self, ix: discord.Interaction):
        await ix.response.send_modal(NewDraftModal(self.gid, self))

    async def _open(self, ix: discord.Interaction):
        did = ix.data["values"][0]
        db = load_announcements(self.gid)
        draft = db.get("drafts", {}).get(did, {})
        view = DraftDetailView(self.gid, did, self)
        await ix.response.edit_message(embed=_draft_embed(draft, self.gid), view=view)


# ── /paradis-announcement ─────────────────────────────────────────────────────

@bot.tree.command(
    name="paradis-announcement",
    description="Create and publish announcements | สร้างและเผยแพร่ประกาศ",
    guild=GUILD2_OBJ,
)
async def announcement_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    if not _can_announce(ix):
        embed = discord.Embed(
            title="Permission Denied",
            description=t(ix.guild_id, "ann_no_permission"),
            color=discord.Color.red(),
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    await ix.response.send_message(
        embed=_list_embed(ix.guild_id),
        view=AnnouncementListView(ix.guild_id),
        ephemeral=True,
    )
