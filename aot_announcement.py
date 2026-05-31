"""Announcement system — /paradis-announcement."""
import time, uuid
import discord
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Modal, TextInput)

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


# ── Modals ────────────────────────────────────────────────────────────────────

class NewDraftModal(Modal, title="New Announcement"):
    f_name = TextInput(label="Announcement Name", max_length=80)

    def __init__(self, gid, parent):
        super().__init__()
        self.gid = gid; self.parent = parent
        self.f_name.label = t(gid, "draft_name_field")

    async def on_submit(self, ix):
        name = self.f_name.value.strip()
        if not name: await ix.response.defer(); return
        db = load_announcements(self.gid)
        draft_id = str(uuid.uuid4())[:8]
        db["drafts"][draft_id] = {
            "name": name, "title": name, "content": "",
            "author_id": str(ix.user.id), "created_at": time.time(),
        }
        save_announcements(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class EditTitleModal(Modal, title="Edit Title"):
    f_title = TextInput(label="Title", max_length=100)

    def __init__(self, gid, draft_id, parent):
        super().__init__()
        self.gid = gid; self.draft_id = draft_id; self.parent = parent
        self.f_title.label = t(gid, "ann_title_field")

    async def on_submit(self, ix):
        db = load_announcements(self.gid)
        if self.draft_id in db["drafts"]:
            db["drafts"][self.draft_id]["title"] = self.f_title.value.strip()
            save_announcements(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


class EditContentModal(Modal, title="Edit Content"):
    f_content = TextInput(label="Content", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, gid, draft_id, parent):
        super().__init__()
        self.gid = gid; self.draft_id = draft_id; self.parent = parent
        self.f_content.label = t(gid, "ann_content_field")

    async def on_submit(self, ix):
        db = load_announcements(self.gid)
        if self.draft_id in db["drafts"]:
            db["drafts"][self.draft_id]["content"] = self.f_content.value.strip()
            save_announcements(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Draft detail view ─────────────────────────────────────────────────────────

class DraftDetailView(LayoutView):
    def __init__(self, gid, draft_id, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.draft_id = draft_id; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        db    = load_announcements(self.gid)
        draft = db.get("drafts", {}).get(self.draft_id)
        if not draft:
            self.add_item(Container(TextDisplay("Draft not found."))); return

        title   = draft.get("title",   "*(no title)*")
        content = draft.get("content", "*(no content)*") or "*(no content)*"
        text = "\n".join([
            f"**📢 {draft['name']}**",
            "",
            f"**Title:** {title}",
            "",
            f"**Content:**",
            content[:800] + ("…" if len(content) > 800 else ""),
        ])

        et_btn  = Button(label=t(self.gid, "edit_title_btn"),   style=discord.ButtonStyle.secondary, custom_id="dd_et")
        ec_btn  = Button(label=t(self.gid, "edit_content_btn"), style=discord.ButtonStyle.secondary, custom_id="dd_ec")
        pub_btn = Button(label=t(self.gid, "publish_btn"),       style=discord.ButtonStyle.green,     custom_id="dd_pub")
        del_btn = Button(label=t(self.gid, "delete_draft_btn"),  style=discord.ButtonStyle.danger,    custom_id="dd_del")
        bk_btn  = Button(label=t(self.gid, "back_btn"),          style=discord.ButtonStyle.secondary, custom_id="dd_bk")
        et_btn.callback  = self._edit_title
        ec_btn.callback  = self._edit_content
        pub_btn.callback = self._publish
        del_btn.callback = self._delete
        bk_btn.callback  = self._back

        self.add_item(Container(
            TextDisplay(text), Separator(),
            ActionRow(et_btn, ec_btn),
            ActionRow(pub_btn),
            ActionRow(del_btn, bk_btn),
        ))

    async def _edit_title(self, ix):
        db    = load_announcements(self.gid)
        draft = db.get("drafts", {}).get(self.draft_id, {})
        m = EditTitleModal(self.gid, self.draft_id, self)
        m.f_title.default = draft.get("title", "")
        await ix.response.send_modal(m)

    async def _edit_content(self, ix):
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

        from discord.ui import MediaGallery
        from discord.components import MediaGalleryItem

        pub_view = LayoutView(timeout=None)
        pub_view.add_item(Container(
            TextDisplay(f"**📢 {title}**\n\n{content}"),
        ))

        sent = 0
        for cid in channels:
            ch = ix.guild.get_channel(int(cid))
            if ch:
                try:
                    await ch.send(view=pub_view)
                    sent += 1
                except Exception:
                    pass

        await ix.response.send_message(
            f"✅ {t(self.gid, 'ann_published')} Sent to {sent} channel(s).", ephemeral=True)

    async def _delete(self, ix):
        db = load_announcements(self.gid)
        db["drafts"].pop(self.draft_id, None)
        save_announcements(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Draft list view ───────────────────────────────────────────────────────────

class AnnouncementListView(LayoutView):
    def __init__(self, gid):
        super().__init__(timeout=300)
        self.gid = gid
        self._build()

    def _build(self):
        self.clear_items()
        db     = load_announcements(self.gid)
        drafts = db.get("drafts", {})

        lines = [f"**{t(self.gid,'announcement_title')}**", ""]
        if drafts:
            for did, d in list(drafts.items())[:10]:
                lines.append(f"• **{d['name']}** — `{did}`")
        else:
            lines.append(t(self.gid, "no_drafts"))

        create_btn = Button(label=t(self.gid, "create_draft_btn"),
                            style=discord.ButtonStyle.green, custom_id="al_create")
        create_btn.callback = self._create

        children = [TextDisplay("\n".join(lines)), Separator(), ActionRow(create_btn)]

        if drafts:
            opts = [discord.SelectOption(label=d["name"][:100], value=did)
                    for did, d in list(drafts.items())[:25]]
            sel = discord.ui.Select(placeholder="Open draft…", options=opts)
            sel.callback = self._open
            children.insert(2, ActionRow(sel))

        self.add_item(Container(*children))

    async def _create(self, ix):
        await ix.response.send_modal(NewDraftModal(self.gid, self))

    async def _open(self, ix):
        did = ix.data["values"][0]
        await ix.response.edit_message(view=DraftDetailView(self.gid, did, self))


# ── /paradis-announcement ─────────────────────────────────────────────────────

@bot.tree.command(name="paradis-announcement",
                  description="Create and publish announcements",
                  guild=GUILD2_OBJ)
async def announcement_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    if not _can_announce(ix):
        v = LayoutView(timeout=60)
        v.add_item(Container(TextDisplay(t(ix.guild_id, "ann_no_permission"))))
        await ix.response.send_message(view=v, ephemeral=True)
        return
    await ix.response.send_message(view=AnnouncementListView(ix.guild_id), ephemeral=True)
