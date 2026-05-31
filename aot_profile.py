"""Profile command — registration, display, inventory, backstory, journal tabs."""
import asyncio, time, uuid
import discord
from discord.ui import LayoutView, Container, TextDisplay, Separator, ActionRow, Button, Select, Modal, TextInput, Section, Thumbnail, MediaGallery
from discord.components import MediaGalleryItem

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_players, save_players, load_config, load_items,
    select_options_from_list, get_available_bloodlines,
    has_shifter_access, assign_roles, remove_old_roles,
    format_profile_text, cv2_dm, is_url,
    get_faction_names, get_visible_ranks_for_faction, get_faction_emblem,
    log_event,
)


# ── Registration modal (Step 1) ───────────────────────────────────────────────

class RegisterModal(Modal, title="Register"):
    char_name  = TextInput(label="Name",       max_length=60)
    age        = TextInput(label="Age",        max_length=10)
    gender     = TextInput(label="Gender",     max_length=30)
    appearance = TextInput(label="Appearance", style=discord.TextStyle.paragraph, max_length=500)
    image      = TextInput(label="Image (URL or emoji, optional)", max_length=300, required=False)

    def __init__(self, guild_id: int, prefill: dict = None):
        super().__init__()
        self.guild_id = guild_id
        gid = guild_id
        self.char_name.label  = t(gid, "name_field")
        self.age.label        = t(gid, "age_field")
        self.gender.label     = t(gid, "gender_field")
        self.appearance.label = t(gid, "appearance_field")
        self.image.label      = t(gid, "image_field")
        if prefill:
            self.char_name.default  = prefill.get("name", "")
            self.age.default        = prefill.get("age", "")
            self.gender.default     = prefill.get("gender", "")
            self.appearance.default = prefill.get("appearance", "")
            self.image.default      = prefill.get("image", "")

    async def on_submit(self, ix: discord.Interaction):
        gid = self.guild_id
        uid = ix.user.id
        step1 = {
            "name":       self.char_name.value.strip(),
            "age":        self.age.value.strip(),
            "gender":     self.gender.value.strip(),
            "appearance": self.appearance.value.strip(),
            "image":      (self.image.value or "").strip(),
        }
        cfg        = load_config(gid)
        bloodlines = get_available_bloodlines(gid, uid)
        existing   = load_players(gid).get(str(uid), {})
        view = RegisterSelectsView(gid, uid, step1, cfg, bloodlines,
                                   existing_player=existing, is_edit=bool(existing))
        await ix.response.edit_message(view=view)


# ── Step 2: dropdowns ─────────────────────────────────────────────────────────

class RegisterSelectsView(LayoutView):
    def __init__(self, gid, uid, step1, cfg, bloodlines,
                 existing_player=None, is_edit=False):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.step1 = step1
        self.cfg = cfg; self.bloodlines = bloodlines
        self.existing = existing_player or {}; self.is_edit = is_edit

        factions = get_faction_names(gid)
        self.sel_faction   = self.existing.get("faction", factions[0] if factions else "")
        vis_ranks          = get_visible_ranks_for_faction(gid, self.sel_faction, uid)
        self.sel_rank      = self.existing.get("rank", vis_ranks[0] if vis_ranks else "")
        self.sel_bloodline = self.existing.get("bloodline", bloodlines[0] if bloodlines else "")
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        factions  = get_faction_names(gid)
        vis_ranks = get_visible_ranks_for_faction(gid, self.sel_faction, self.uid)

        sf = Select(placeholder=t(gid, "select_faction"),
                    options=select_options_from_list(factions, self.sel_faction))
        sf.callback = self._faction_cb

        sr = Select(placeholder=t(gid, "select_rank"),
                    options=select_options_from_list(vis_ranks, self.sel_rank))
        sr.callback = self._rank_cb

        sb = Select(placeholder=t(gid, "select_bloodline"),
                    options=select_options_from_list(self.bloodlines, self.sel_bloodline))
        sb.callback = self._bloodline_cb

        confirm = Button(label=t(gid, "confirm_btn"), style=discord.ButtonStyle.green, custom_id="reg_confirm")
        confirm.callback = self._confirm

        container_children = [
            TextDisplay(f"**{t(gid,'profile_title')}**\n\n{t(gid,'register_step2')}"),
            Separator(),
            ActionRow(sf),
            ActionRow(sr),
            ActionRow(sb),
            ActionRow(confirm),
        ]
        self.add_item(Container(*container_children))

    async def _faction_cb(self, ix):
        self.sel_faction = ix.data["values"][0]
        vis_ranks = get_visible_ranks_for_faction(self.gid, self.sel_faction, self.uid)
        self.sel_rank = vis_ranks[0] if vis_ranks else ""
        self._build()
        await ix.response.edit_message(view=self)

    async def _rank_cb(self, ix):
        self.sel_rank = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _bloodline_cb(self, ix):
        self.sel_bloodline = ix.data["values"][0]; self._build()
        await ix.response.edit_message(view=self)

    async def _confirm(self, ix: discord.Interaction):
        gid, uid = self.gid, self.uid
        players = load_players(gid)
        cfg     = load_config(gid)
        old     = players.get(str(uid), {})

        player = {**self.step1,
                  "faction":    self.sel_faction,
                  "rank":       self.sel_rank,
                  "bloodline":  self.sel_bloodline,
                  "shifter":    old.get("shifter", "None"),
                  "inventory":  old.get("inventory", {}),
                  "titan_powers": old.get("titan_powers", []),
                  "stamina":    old.get("stamina", 100),
                  "max_stamina": old.get("max_stamina", 100),
                  "ability_cooldowns": old.get("ability_cooldowns", {}),
                  "transformed": False,
                  "deceased":   old.get("deceased", False)}
        players[str(uid)] = player
        save_players(gid, players)

        member = ix.guild.get_member(uid)
        if member:
            if self.is_edit and old:
                await remove_old_roles(member, old, cfg)
            await assign_roles(member, player, cfg)

        name = ix.user.display_name
        view = ProfileView(uid, gid, name)
        await ix.response.edit_message(view=view)

        action = "updated_msg" if self.is_edit else "registered_msg"
        try:
            msg = await ix.channel.send(t(gid, action, name=name, char=player["name"]))
            await asyncio.sleep(30)
            await msg.delete()
        except Exception:
            pass
        profile_text = format_profile_text(player, name, gid)
        await cv2_dm(ix.user, t(gid, "dm_profile", profile=profile_text))


# ── Profile view (tabs) ───────────────────────────────────────────────────────

class ProfileView(LayoutView):
    def __init__(self, user_id: int, guild_id: int, display_name: str = ""):
        super().__init__(timeout=300)
        self.uid = user_id; self.gid = guild_id
        self.display_name = display_name
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid
        players = load_players(gid)
        player  = players.get(str(self.uid), {})
        text = format_profile_text(player, self.display_name or "Character", gid)

        faction = player.get("faction", "")
        emblem_url = get_faction_emblem(gid, faction)
        char_img = player.get("image", "").strip()

        pb = Button(label=t(gid, "show_profile_btn"), style=discord.ButtonStyle.primary,   custom_id="pf_profile")
        pb.callback = self._profile_tab
        ib = Button(label=t(gid, "inventory_btn"),  style=discord.ButtonStyle.secondary, custom_id="pf_inventory")
        ib.callback = self._inventory_tab
        bsb = Button(label=t(gid, "backstory_tab"), style=discord.ButtonStyle.secondary, custom_id="pf_backstory")
        bsb.callback = self._backstory_tab
        jb  = Button(label=t(gid, "journal_tab"),   style=discord.ButtonStyle.secondary, custom_id="pf_journal")
        jb.callback  = self._journal_tab
        eb = Button(label=t(gid, "edit_btn"),       style=discord.ButtonStyle.secondary, custom_id="pf_edit")
        eb.callback = self._edit

        if emblem_url:
            main_block = Section(TextDisplay(text), accessory=Thumbnail(media=emblem_url))
        else:
            main_block = TextDisplay(text)

        container_children = [main_block, Separator()]
        if char_img and is_url(char_img):
            container_children.append(MediaGallery(MediaGalleryItem(media=char_img)))
            container_children.append(Separator())
        container_children.append(ActionRow(pb, ib, bsb))
        container_children.append(ActionRow(jb, eb))

        self.add_item(Container(*container_children))

    async def _profile_tab(self, ix: discord.Interaction):
        gid = self.gid
        players = load_players(gid)
        player  = players.get(str(self.uid), {})
        text = format_profile_text(player, self.display_name or "Character", gid)

        faction = player.get("faction", "")
        emblem_url = get_faction_emblem(gid, faction)
        char_img = player.get("image", "").strip()

        full_text = f"<@{self.uid}>\n{text}"

        if emblem_url:
            main_block = Section(TextDisplay(full_text), accessory=Thumbnail(media=emblem_url))
        else:
            main_block = TextDisplay(full_text)

        container_children = [main_block]
        if char_img and is_url(char_img):
            container_children.append(Separator())
            container_children.append(MediaGallery(MediaGalleryItem(media=char_img)))

        pub_view = LayoutView(timeout=None)
        pub_view.add_item(Container(*container_children))

        await ix.response.defer(ephemeral=True)
        try:
            await ix.channel.send(view=pub_view)
        except Exception:
            pass

    async def _inventory_tab(self, ix: discord.Interaction):
        from aot_items import InventoryView
        await ix.response.edit_message(view=InventoryView(self.uid, self.gid, self))

    async def _backstory_tab(self, ix: discord.Interaction):
        await ix.response.edit_message(view=BackstoryView(self.uid, self.gid, self))

    async def _journal_tab(self, ix: discord.Interaction):
        await ix.response.edit_message(view=JournalView(self.uid, self.gid, self))

    async def _edit(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(RegisterModal(self.gid, prefill=player))


# ── Backstory View ───────────────────────────────────────────────────────────

class BackstoryView(LayoutView):
    def __init__(self, uid: int, gid: int, parent):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        player    = load_players(self.gid).get(str(self.uid), {})
        backstory = player.get("backstory", "").strip()
        text      = f"**{t(self.gid,'backstory_tab')}**\n\n{backstory or t(self.gid,'backstory_empty')}"

        bk_btn   = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="bs_bk")
        edit_btn = Button(label=t(self.gid, "edit_backstory_btn"), style=discord.ButtonStyle.primary, custom_id="bs_edit")
        bk_btn.callback   = self._back
        edit_btn.callback = self._edit

        self.add_item(Container(
            ActionRow(bk_btn), Separator(),
            TextDisplay(text), Separator(),
            ActionRow(edit_btn),
        ))

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _edit(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(BackstoryEditModal(self.uid, self.gid,
                                                         player.get("backstory", ""), self))


class BackstoryEditModal(Modal, title="Edit Backstory"):
    f_text = TextInput(label="Backstory", style=discord.TextStyle.paragraph,
                       max_length=2000, required=False)

    def __init__(self, uid, gid, current, parent):
        super().__init__(); self.uid = uid; self.gid = gid; self.parent = parent
        self.f_text.label   = t(gid, "backstory_field")
        self.f_text.default = current

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["backstory"] = self.f_text.value.strip()
        players[str(self.uid)] = player
        save_players(self.gid, players)
        await log_event(bot, self.gid, "profile",
                        f"<@{self.uid}> updated backstory")
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Journal View ──────────────────────────────────────────────────────────────

_JOURNAL_PER_PAGE = 3


class JournalView(LayoutView):
    def __init__(self, uid: int, gid: int, parent, page: int = 0):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.parent = parent; self.page = page
        self.sel_entry = None
        self._build()

    def _build(self):
        self.clear_items()
        player  = load_players(self.gid).get(str(self.uid), {})
        entries = player.get("journal", [])
        total   = max(1, (len(entries) + _JOURNAL_PER_PAGE - 1) // _JOURNAL_PER_PAGE)
        self.page = max(0, min(self.page, total - 1))
        chunk = list(reversed(entries))[
            self.page * _JOURNAL_PER_PAGE:(self.page + 1) * _JOURNAL_PER_PAGE
        ]

        lines = [f"**{t(self.gid,'journal_tab')}**",
                 t(self.gid, "page_label", page=self.page + 1, total=total), ""]
        if not chunk:
            lines.append(t(self.gid, "journal_empty"))
        for e in chunk:
            vis = "🌐" if e.get("public") else "🔒"
            ts  = time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0)))
            lines.append(f"{vis} **{ts}**")
            lines.append(e.get("content", "")[:200])
            lines.append("")

        bk_btn   = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="jv_bk")
        add_btn  = Button(label=t(self.gid, "add_journal_btn"), style=discord.ButtonStyle.green, custom_id="jv_add")
        prev_btn = Button(label=t(self.gid, "prev_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="jv_prev", disabled=(self.page == 0))
        next_btn = Button(label=t(self.gid, "next_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="jv_next", disabled=(self.page >= total - 1))
        bk_btn.callback   = self._back
        add_btn.callback  = self._add
        prev_btn.callback = self._prev
        next_btn.callback = self._next

        children = [
            ActionRow(bk_btn), Separator(),
            TextDisplay("\n".join(lines)), Separator(),
            ActionRow(add_btn),
            ActionRow(prev_btn, next_btn),
        ]

        if chunk:
            opts = [discord.SelectOption(
                        label=time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0)))[:100],
                        value=e["id"])
                    for e in chunk if "id" in e]
            if opts:
                del_sel = Select(placeholder="Select entry to delete/toggle", options=opts)
                del_sel.callback = self._manage_entry
                children.insert(-1, ActionRow(del_sel))

        self.add_item(Container(*children))

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _add(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        await ix.response.send_modal(JournalAddModal(self.uid, self.gid, self))

    async def _manage_entry(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True); return
        entry_id = ix.data["values"][0]
        await ix.response.edit_message(
            view=JournalEntryManageView(self.uid, self.gid, entry_id, self))

    async def _prev(self, ix): self.page -= 1; self._build(); await ix.response.edit_message(view=self)
    async def _next(self, ix): self.page += 1; self._build(); await ix.response.edit_message(view=self)


class JournalAddModal(Modal, title="Add Journal Entry"):
    f_content = TextInput(label="Entry", style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, uid, gid, parent):
        super().__init__(); self.uid = uid; self.gid = gid; self.parent = parent
        self.f_content.label = t(gid, "journal_entry_field")

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        entry   = {"id": str(uuid.uuid4())[:8], "content": self.f_content.value.strip(),
                   "ts": time.time(), "public": False}
        player.setdefault("journal", []).append(entry)
        players[str(self.uid)] = player
        save_players(self.gid, players)
        await log_event(bot, self.gid, "profile", f"<@{self.uid}> added a journal entry")
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class JournalEntryManageView(LayoutView):
    def __init__(self, uid, gid, entry_id, parent):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.entry_id = entry_id; self.parent = parent
        players = load_players(gid)
        player  = players.get(str(uid), {})
        entry   = next((e for e in player.get("journal", []) if e.get("id") == entry_id), {})
        is_pub  = entry.get("public", False)
        text    = f"**Entry:** {entry.get('content','')[:300]}"
        toggle_label = t(gid, "journal_private_btn") if is_pub else t(gid, "journal_public_btn")
        toggle_btn = Button(label=toggle_label, style=discord.ButtonStyle.secondary, custom_id="jem_toggle")
        delete_btn = Button(label=t(gid, "journal_delete_btn"), style=discord.ButtonStyle.danger, custom_id="jem_del")
        bk_btn     = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="jem_bk")
        toggle_btn.callback = self._toggle
        delete_btn.callback = self._delete
        bk_btn.callback     = self._back
        self.add_item(Container(ActionRow(bk_btn), Separator(), TextDisplay(text), Separator(),
                                ActionRow(toggle_btn, delete_btn)))

    async def _toggle(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        for e in player.get("journal", []):
            if e.get("id") == self.entry_id:
                e["public"] = not e.get("public", False); break
        save_players(self.gid, players)
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _delete(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["journal"] = [e for e in player.get("journal", []) if e.get("id") != self.entry_id]
        save_players(self.gid, players)
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Unregistered view ─────────────────────────────────────────────────────────

class UnregisteredView(LayoutView):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.gid = guild_id
        rb = Button(label=t(guild_id, "register_btn"), style=discord.ButtonStyle.green, custom_id="unreg_register")
        rb.callback = self._register
        self.add_item(Container(
            TextDisplay(f"**{t(guild_id,'profile_title')}**\n\n{t(guild_id,'not_registered')}"),
            Separator(),
            ActionRow(rb),
        ))

    async def _register(self, ix: discord.Interaction):
        await ix.response.send_modal(RegisterModal(self.gid))


# ── /profile command ──────────────────────────────────────────────────────────

@bot.tree.command(name="profile", description="View or create your character profile", guild=GUILD2_OBJ)
async def profile_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    gid = ix.guild_id; uid = ix.user.id
    player = load_players(gid).get(str(uid))
    if not player:
        await ix.response.send_message(view=UnregisteredView(gid), ephemeral=True)
    else:
        await ix.response.send_message(view=ProfileView(uid, gid, ix.user.display_name), ephemeral=True)
