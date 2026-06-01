"""Profile command — registration, display, inventory, backstory, journal tabs."""
import asyncio
import json
import time
import uuid
from pathlib import Path

import discord

from core.instance import bot
from core.shared import (
    t,
    load_players,
    save_players,
    load_config,
    load_items,
    select_options_from_list,
    get_available_bloodlines,
    assign_roles,
    remove_old_roles,
    format_profile_text,
    format_inventory_text,
    is_url,
    get_faction_names,
    get_visible_ranks_for_faction,
    get_faction_emblem,
    log_event,
    EMBED_COLOR,
)


# ── Forum character creation helpers ─────────────────────────────────────────

def _pending_path(gid: int) -> Path:
    return Path(f"data/pending_{gid}.json")


def _load_pending(gid: int) -> dict:
    p = _pending_path(gid)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_pending(gid: int, data: dict):
    p = _pending_path(gid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile_embed(player: dict, display_name: str, gid: int) -> discord.Embed:
    """Build a rich Embed for the given player's profile."""
    char_name = player.get("name") or display_name
    balance   = player.get("balance", 0)

    embed = discord.Embed(
        title=char_name,
        color=EMBED_COLOR,
    )

    # Faction emblem as thumbnail
    faction    = player.get("faction", "")
    emblem_url = get_faction_emblem(gid, faction)
    if emblem_url and is_url(emblem_url):
        embed.set_thumbnail(url=emblem_url)

    # Character image as main image
    char_img = player.get("image", "").strip()
    if char_img and is_url(char_img):
        embed.set_image(url=char_img)

    embed.add_field(name=t(gid, "name_label"),       value=player.get("name", "?"),       inline=True)
    embed.add_field(name=t(gid, "age_label"),         value=player.get("age", "?"),         inline=True)
    embed.add_field(name=t(gid, "gender_label"),      value=player.get("gender", "?"),      inline=True)
    embed.add_field(name=t(gid, "bloodline_label"),   value=player.get("bloodline", "?"),   inline=True)
    embed.add_field(name=t(gid, "faction_label"),     value=player.get("faction", "?"),     inline=True)
    embed.add_field(name=t(gid, "rank_label"),        value=player.get("rank", "?"),        inline=True)

    if balance > 0:
        embed.add_field(name=t(gid, "balance_label"), value=str(balance), inline=True)

    appearance = player.get("appearance", "?")
    embed.add_field(name=t(gid, "appearance_label"),  value=f"*{appearance}*",              inline=False)

    embed.set_footer(text=display_name)
    return embed


def _inventory_embed(player: dict, gid: int) -> discord.Embed:
    """Build an inventory Embed."""
    items_data = load_items(gid)
    text       = format_inventory_text(player, items_data, gid)
    embed      = discord.Embed(description=text, color=EMBED_COLOR)
    return embed


def _check_creation_role(ix: discord.Interaction) -> str | None:
    """
    Returns the role name if the user is MISSING the required creation role,
    or None if access is allowed.
    """
    gid = ix.guild_id
    cfg = load_config(gid)
    role_id = cfg.get("character_creation_role")
    if not role_id:
        return None  # no gate configured
    member = ix.guild.get_member(ix.user.id) if ix.guild else None
    if member is None:
        return str(role_id)
    role = ix.guild.get_role(int(role_id))
    if role is None:
        return str(role_id)
    if role not in member.roles:
        return role.name
    return None


# ── Registration modal (Step 1) ───────────────────────────────────────────────

class RegisterModal(discord.ui.Modal, title="Register"):
    char_name  = discord.ui.TextInput(label="Name",       max_length=60)
    age        = discord.ui.TextInput(label="Age",        max_length=10)
    gender     = discord.ui.TextInput(label="Gender",     max_length=30)
    appearance = discord.ui.TextInput(label="Appearance", style=discord.TextStyle.paragraph, max_length=500)
    image      = discord.ui.TextInput(label="Image (URL or emoji, optional)", max_length=300, required=False)

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

        # Check creation role gate
        missing_role = _check_creation_role(ix)
        if missing_role:
            embed = discord.Embed(
                description=t(gid, "no_creation_role", role=missing_role),
                color=0xFF0000,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

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
        embed = discord.Embed(
            title=t(gid, "profile_title"),
            description=t(gid, "register_step2"),
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)


# ── Step 2: dropdowns ─────────────────────────────────────────────────────────

class RegisterSelectsView(discord.ui.View):
    def __init__(self, gid, uid, step1, cfg, bloodlines,
                 existing_player=None, is_edit=False):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.step1 = step1
        self.cfg = cfg
        self.bloodlines = bloodlines
        self.existing = existing_player or {}
        self.is_edit = is_edit

        factions          = get_faction_names(gid)
        self.sel_faction  = self.existing.get("faction", factions[0] if factions else "")
        vis_ranks         = get_visible_ranks_for_faction(gid, self.sel_faction, uid)
        self.sel_rank     = self.existing.get("rank", vis_ranks[0] if vis_ranks else "")
        self.sel_bloodline = self.existing.get("bloodline", bloodlines[0] if bloodlines else "")
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        factions  = get_faction_names(gid)
        vis_ranks = get_visible_ranks_for_faction(gid, self.sel_faction, self.uid)

        faction_sel = discord.ui.Select(
            placeholder=t(gid, "select_faction"),
            options=select_options_from_list(factions, self.sel_faction),
            row=0,
        )
        faction_sel.callback = self._faction_cb
        self.add_item(faction_sel)

        rank_sel = discord.ui.Select(
            placeholder=t(gid, "select_rank"),
            options=select_options_from_list(vis_ranks, self.sel_rank),
            row=1,
        )
        rank_sel.callback = self._rank_cb
        self.add_item(rank_sel)

        bloodline_sel = discord.ui.Select(
            placeholder=t(gid, "select_bloodline"),
            options=select_options_from_list(self.bloodlines, self.sel_bloodline),
            row=2,
        )
        bloodline_sel.callback = self._bloodline_cb
        self.add_item(bloodline_sel)

        confirm_btn = discord.ui.Button(
            label=t(gid, "confirm_btn"),
            style=discord.ButtonStyle.green,
            row=3,
        )
        confirm_btn.callback = self._confirm
        self.add_item(confirm_btn)

    async def _faction_cb(self, ix: discord.Interaction):
        self.sel_faction = ix.data["values"][0]
        vis_ranks = get_visible_ranks_for_faction(self.gid, self.sel_faction, self.uid)
        self.sel_rank = vis_ranks[0] if vis_ranks else ""
        self._build()
        await ix.response.edit_message(view=self)

    async def _rank_cb(self, ix: discord.Interaction):
        self.sel_rank = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(view=self)

    async def _bloodline_cb(self, ix: discord.Interaction):
        self.sel_bloodline = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(view=self)

    async def _confirm(self, ix: discord.Interaction):
        gid, uid = self.gid, self.uid
        players  = load_players(gid)
        cfg      = load_config(gid)
        old      = players.get(str(uid), {})

        player = {
            **self.step1,
            "faction":           self.sel_faction,
            "rank":              self.sel_rank,
            "bloodline":         self.sel_bloodline,
            "shifter":           old.get("shifter", "None"),
            "inventory":         old.get("inventory", {}),
            "titan_powers":      old.get("titan_powers", []),
            "stamina":           old.get("stamina", 100),
            "max_stamina":       old.get("max_stamina", 100),
            "ability_cooldowns": old.get("ability_cooldowns", {}),
            "transformed":       False,
            "deceased":          old.get("deceased", False),
        }
        players[str(uid)] = player
        save_players(gid, players)

        member = ix.guild.get_member(uid)
        if member:
            if self.is_edit and old:
                await remove_old_roles(member, old, cfg)
            await assign_roles(member, player, cfg)

        display_name = ix.user.display_name
        embed        = _profile_embed(player, display_name, gid)
        view         = ProfileView(uid, gid, display_name, is_admin=ix.user.guild_permissions.administrator)
        await ix.response.edit_message(embed=embed, view=view)

        action = "updated_msg" if self.is_edit else "registered_msg"
        try:
            msg = await ix.channel.send(t(gid, action, name=display_name, char=player["name"]))
            await asyncio.sleep(30)
            await msg.delete()
        except Exception:
            pass

        profile_text = format_profile_text(player, display_name, gid)
        try:
            dm_embed = discord.Embed(
                description=t(gid, "dm_profile", profile=profile_text),
                color=EMBED_COLOR,
            )
            await ix.user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass


# ── Profile View (tabs) ───────────────────────────────────────────────────────

class ProfileView(discord.ui.View):
    """Main tabbed profile view using discord.Embed + discord.ui.View."""

    def __init__(self, user_id: int, guild_id: int, display_name: str = "", is_admin: bool = False):
        super().__init__(timeout=300)
        self.uid          = user_id
        self.gid          = guild_id
        self.display_name = display_name
        self.is_admin     = is_admin
        self._apply_labels()

    def _apply_labels(self):
        """Localise button labels after construction."""
        gid = self.gid
        self.btn_profile.label   = t(gid, "show_profile_btn")
        self.btn_inventory.label = t(gid, "inventory_btn")
        self.btn_backstory.label = t(gid, "backstory_tab")
        self.btn_journal.label   = t(gid, "journal_tab")
        self.btn_edit.label      = t(gid, "edit_btn")
        if self.is_admin:
            self.btn_view_player.label = t(gid, "admin_view_profile_btn")
            self.btn_flag_dead.label   = t(gid, "admin_flag_death_btn")
        else:
            # Remove admin buttons if not admin
            self.remove_item(self.btn_view_player)
            self.remove_item(self.btn_flag_dead)

    # ── Row 0 buttons ─────────────────────────────────────────────────────────

    @discord.ui.button(label="📋 Show Profile", style=discord.ButtonStyle.primary, row=0)
    async def btn_profile(self, ix: discord.Interaction, button: discord.ui.Button):
        gid     = self.gid
        players = load_players(gid)
        player  = players.get(str(self.uid), {})
        embed   = _profile_embed(player, self.display_name or "Character", gid)
        # Post a public copy in the channel
        try:
            await ix.response.defer(ephemeral=True)
            await ix.channel.send(
                content=f"<@{self.uid}>",
                embed=embed,
            )
        except Exception:
            pass

    @discord.ui.button(label="🎒 Inventory", style=discord.ButtonStyle.secondary, row=0)
    async def btn_inventory(self, ix: discord.Interaction, button: discord.ui.Button):
        gid     = self.gid
        players = load_players(gid)
        player  = players.get(str(self.uid), {})
        embed   = _inventory_embed(player, gid)
        view    = InventoryTabView(self.uid, gid, self)
        await ix.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="📖 Backstory", style=discord.ButtonStyle.secondary, row=0)
    async def btn_backstory(self, ix: discord.Interaction, button: discord.ui.Button):
        gid    = self.gid
        player = load_players(gid).get(str(self.uid), {})
        embed  = _backstory_embed(player, gid)
        view   = BackstoryView(self.uid, gid, self)
        await ix.response.edit_message(embed=embed, view=view)

    # ── Row 1 buttons ─────────────────────────────────────────────────────────

    @discord.ui.button(label="📔 Journal", style=discord.ButtonStyle.secondary, row=1)
    async def btn_journal(self, ix: discord.Interaction, button: discord.ui.Button):
        view  = JournalView(self.uid, self.gid, self)
        embed = view.build_embed()
        await ix.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="✏️ Edit Profile", style=discord.ButtonStyle.secondary, row=1)
    async def btn_edit(self, ix: discord.Interaction, button: discord.ui.Button):
        if ix.user.id != self.uid:
            embed = discord.Embed(description=t(self.gid, "not_your_profile"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(RegisterModal(self.gid, prefill=player))

    # ── Row 2 admin buttons ───────────────────────────────────────────────────

    @discord.ui.button(label="👁️ View Player", style=discord.ButtonStyle.secondary, row=2)
    async def btn_view_player(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid
        if not ix.user.guild_permissions.administrator:
            embed = discord.Embed(description=t(gid, "admin_only"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        view  = AdminViewPlayerSelectView(gid)
        embed = discord.Embed(
            title=t(gid, "admin_view_profile_btn"),
            description="Select a player to view their profile.",
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label="☠️ Flag as Deceased", style=discord.ButtonStyle.danger, row=2)
    async def btn_flag_dead(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid
        if not ix.user.guild_permissions.administrator:
            embed = discord.Embed(description=t(gid, "admin_only"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        view  = AdminFlagDeadSelectView(gid)
        embed = discord.Embed(
            title=t(gid, "admin_flag_death_btn"),
            description="Select the player to flag as deceased.",
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── Inventory Tab View ────────────────────────────────────────────────────────

class InventoryTabView(discord.ui.View):
    """Simple view shown while the inventory tab is active."""

    def __init__(self, uid: int, gid: int, parent: ProfileView):
        super().__init__(timeout=300)
        self.uid    = uid
        self.gid    = gid
        self.parent = parent
        self.btn_back.label = t(gid, "back_btn")

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary)
    async def btn_back(self, ix: discord.Interaction, button: discord.ui.Button):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        embed   = _profile_embed(player, self.parent.display_name or "Character", self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Backstory helpers ─────────────────────────────────────────────────────────

def _backstory_embed(player: dict, gid: int) -> discord.Embed:
    backstory = player.get("backstory", "").strip()
    embed = discord.Embed(
        title=t(gid, "backstory_tab"),
        description=backstory or t(gid, "backstory_empty"),
        color=EMBED_COLOR,
    )
    return embed


# ── Backstory View ────────────────────────────────────────────────────────────

class BackstoryView(discord.ui.View):
    def __init__(self, uid: int, gid: int, parent: ProfileView):
        super().__init__(timeout=300)
        self.uid    = uid
        self.gid    = gid
        self.parent = parent
        self.btn_back.label        = t(gid, "back_btn")
        self.btn_edit_bs.label     = t(gid, "edit_backstory_btn")

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix: discord.Interaction, button: discord.ui.Button):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        embed   = _profile_embed(player, self.parent.display_name or "Character", self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)

    @discord.ui.button(label="✏️ Edit Backstory", style=discord.ButtonStyle.primary, row=0)
    async def btn_edit_bs(self, ix: discord.Interaction, button: discord.ui.Button):
        if ix.user.id != self.uid:
            embed = discord.Embed(description=t(self.gid, "not_your_profile"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(
            BackstoryEditModal(self.uid, self.gid, player.get("backstory", ""), self)
        )


class BackstoryEditModal(discord.ui.Modal, title="Edit Backstory"):
    f_text = discord.ui.TextInput(
        label="Backstory",
        style=discord.TextStyle.paragraph,
        max_length=2000,
        required=False,
    )

    def __init__(self, uid: int, gid: int, current: str, parent: BackstoryView):
        super().__init__()
        self.uid    = uid
        self.gid    = gid
        self.parent = parent
        self.f_text.label   = t(gid, "backstory_field")
        self.f_text.default = current

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["backstory"] = self.f_text.value.strip()
        players[str(self.uid)] = player
        save_players(self.gid, players)
        await log_event(bot, self.gid, "profile", f"<@{self.uid}> updated backstory")
        embed = _backstory_embed(player, self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Journal helpers ───────────────────────────────────────────────────────────

_JOURNAL_PER_PAGE = 3


def _journal_embed(uid: int, gid: int, page: int) -> tuple[discord.Embed, int]:
    """Return (embed, total_pages)."""
    player  = load_players(gid).get(str(uid), {})
    entries = player.get("journal", [])
    total   = max(1, (len(entries) + _JOURNAL_PER_PAGE - 1) // _JOURNAL_PER_PAGE)
    page    = max(0, min(page, total - 1))
    chunk   = list(reversed(entries))[
        page * _JOURNAL_PER_PAGE:(page + 1) * _JOURNAL_PER_PAGE
    ]

    embed = discord.Embed(
        title=t(gid, "journal_tab"),
        color=EMBED_COLOR,
    )
    embed.set_footer(text=t(gid, "page_label", page=page + 1, total=total))

    if not chunk:
        embed.description = t(gid, "journal_empty")
    else:
        for e in chunk:
            vis = "🌐" if e.get("public") else "🔒"
            ts  = time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0)))
            content = e.get("content", "")[:300]
            embed.add_field(
                name=f"{vis} {ts}",
                value=content or "—",
                inline=False,
            )

    return embed, total


# ── Journal View ──────────────────────────────────────────────────────────────

class JournalView(discord.ui.View):
    def __init__(self, uid: int, gid: int, parent: ProfileView, page: int = 0):
        super().__init__(timeout=300)
        self.uid    = uid
        self.gid    = gid
        self.parent = parent
        self.page   = page
        self._rebuild()

    def build_embed(self) -> discord.Embed:
        embed, total = _journal_embed(self.uid, self.gid, self.page)
        self.page    = max(0, min(self.page, total - 1))
        return embed

    def _rebuild(self):
        """Re-evaluate button states and entry select after a page change."""
        _, total = _journal_embed(self.uid, self.gid, self.page)
        self.page = max(0, min(self.page, total - 1))

        self.btn_back.label    = t(self.gid, "back_btn")
        self.btn_add.label     = t(self.gid, "add_journal_btn")
        self.btn_prev.label    = t(self.gid, "prev_btn")
        self.btn_next.label    = t(self.gid, "next_btn")
        self.btn_prev.disabled = self.page == 0
        self.btn_next.disabled = self.page >= total - 1

        # Rebuild the entry select dynamically
        # Remove old select if present
        for item in list(self.children):
            if isinstance(item, discord.ui.Select) and item.custom_id == "journal_entry_sel":
                self.remove_item(item)
                break

        player  = load_players(self.gid).get(str(self.uid), {})
        entries = player.get("journal", [])
        chunk   = list(reversed(entries))[
            self.page * _JOURNAL_PER_PAGE:(self.page + 1) * _JOURNAL_PER_PAGE
        ]
        if chunk:
            opts = [
                discord.SelectOption(
                    label=time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0)))[:100],
                    value=e["id"],
                )
                for e in chunk
                if "id" in e
            ]
            if opts:
                entry_sel = discord.ui.Select(
                    placeholder="Select entry to manage…",
                    options=opts,
                    row=2,
                    custom_id="journal_entry_sel",
                )
                entry_sel.callback = self._manage_entry
                self.add_item(entry_sel)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix: discord.Interaction, button: discord.ui.Button):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        embed   = _profile_embed(player, self.parent.display_name or "Character", self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)

    @discord.ui.button(label="➕ Add Entry", style=discord.ButtonStyle.green, row=0)
    async def btn_add(self, ix: discord.Interaction, button: discord.ui.Button):
        if ix.user.id != self.uid:
            embed = discord.Embed(description=t(self.gid, "not_your_profile"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        await ix.response.send_modal(JournalAddModal(self.uid, self.gid, self))

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, row=1)
    async def btn_prev(self, ix: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._rebuild()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=1)
    async def btn_next(self, ix: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._rebuild()
        embed = self.build_embed()
        await ix.response.edit_message(embed=embed, view=self)

    async def _manage_entry(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            embed = discord.Embed(description=t(self.gid, "not_your_profile"), color=0xFF0000)
            await ix.response.send_message(embed=embed, ephemeral=True)
            return
        entry_id = ix.data["values"][0]
        view  = JournalEntryManageView(self.uid, self.gid, entry_id, self)
        embed = view.build_embed()
        await ix.response.edit_message(embed=embed, view=view)


class JournalAddModal(discord.ui.Modal, title="Add Journal Entry"):
    f_content = discord.ui.TextInput(
        label="Entry",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, uid: int, gid: int, parent: JournalView):
        super().__init__()
        self.uid    = uid
        self.gid    = gid
        self.parent = parent
        self.f_content.label = t(gid, "journal_entry_field")

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        entry   = {
            "id":      str(uuid.uuid4())[:8],
            "content": self.f_content.value.strip(),
            "ts":      time.time(),
            "public":  False,
        }
        player.setdefault("journal", []).append(entry)
        players[str(self.uid)] = player
        save_players(self.gid, players)
        await log_event(bot, self.gid, "profile", f"<@{self.uid}> added a journal entry")
        self.parent._rebuild()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)


class JournalEntryManageView(discord.ui.View):
    def __init__(self, uid: int, gid: int, entry_id: str, parent: JournalView):
        super().__init__(timeout=300)
        self.uid      = uid
        self.gid      = gid
        self.entry_id = entry_id
        self.parent   = parent

        players = load_players(gid)
        player  = players.get(str(uid), {})
        self.entry = next(
            (e for e in player.get("journal", []) if e.get("id") == entry_id), {}
        )
        is_pub = self.entry.get("public", False)

        self.btn_toggle.label = (
            t(gid, "journal_private_btn") if is_pub else t(gid, "journal_public_btn")
        )
        self.btn_delete.label = t(gid, "journal_delete_btn")
        self.btn_back.label   = t(gid, "back_btn")

    def build_embed(self) -> discord.Embed:
        gid    = self.gid
        entry  = self.entry
        vis    = "🌐" if entry.get("public") else "🔒"
        ts     = time.strftime("%Y-%m-%d", time.localtime(entry.get("ts", 0)))
        embed  = discord.Embed(
            title=f"{vis} {ts}",
            description=entry.get("content", "")[:1000] or "—",
            color=EMBED_COLOR,
        )
        return embed

    @discord.ui.button(label="🌐 Public", style=discord.ButtonStyle.secondary, row=0)
    async def btn_toggle(self, ix: discord.Interaction, button: discord.ui.Button):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        for e in player.get("journal", []):
            if e.get("id") == self.entry_id:
                e["public"] = not e.get("public", False)
                self.entry  = e
                break
        save_players(self.gid, players)
        self.parent._rebuild()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)

    @discord.ui.button(label="🗑️ Delete", style=discord.ButtonStyle.danger, row=0)
    async def btn_delete(self, ix: discord.Interaction, button: discord.ui.Button):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["journal"] = [
            e for e in player.get("journal", []) if e.get("id") != self.entry_id
        ]
        players[str(self.uid)] = player
        save_players(self.gid, players)
        self.parent._rebuild()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)

    @discord.ui.button(label="◀ Back", style=discord.ButtonStyle.secondary, row=0)
    async def btn_back(self, ix: discord.Interaction, button: discord.ui.Button):
        self.parent._rebuild()
        embed = self.parent.build_embed()
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Admin: View Player Select ─────────────────────────────────────────────────

class AdminViewPlayerSelect(discord.ui.UserSelect):
    def __init__(self, gid: int):
        super().__init__(placeholder="Select a player…", min_values=1, max_values=1)
        self.gid = gid

    async def callback(self, ix: discord.Interaction):
        gid    = self.gid
        target = self.values[0]
        uid    = target.id

        players = load_players(gid)
        player  = players.get(str(uid))
        if not player:
            embed = discord.Embed(
                description=t(gid, "not_registered"),
                color=0xFF0000,
            )
            await ix.response.edit_message(embed=embed, view=None)
            return

        embed = _profile_embed(player, target.display_name, gid)
        await ix.response.edit_message(embed=embed, view=None)


class AdminViewPlayerSelectView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.add_item(AdminViewPlayerSelect(gid))


# ── Admin: Flag as Dead Select ────────────────────────────────────────────────

class AdminFlagDeadSelect(discord.ui.UserSelect):
    def __init__(self, gid: int):
        super().__init__(placeholder="Select a player to flag as deceased…", min_values=1, max_values=1)
        self.gid = gid

    async def callback(self, ix: discord.Interaction):
        gid    = self.gid
        target = self.values[0]
        uid    = target.id

        players = load_players(gid)
        player  = players.get(str(uid))
        if not player:
            embed = discord.Embed(
                description=t(gid, "not_registered"),
                color=0xFF0000,
            )
            await ix.response.edit_message(embed=embed, view=None)
            return

        player_name = player.get("name", target.display_name)
        embed = discord.Embed(
            title=t(gid, "admin_flag_death_btn"),
            description=t(gid, "player_death_confirm", name=player_name),
            color=0xFF6600,
        )
        view = AdminDeathConfirmView(gid, uid, target, player_name)
        await ix.response.edit_message(embed=embed, view=view)


class AdminFlagDeadSelectView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.add_item(AdminFlagDeadSelect(gid))


class AdminDeathConfirmView(discord.ui.View):
    def __init__(self, gid: int, target_uid: int, target_user: discord.User, player_name: str):
        super().__init__(timeout=60)
        self.gid         = gid
        self.target_uid  = target_uid
        self.target_user = target_user
        self.player_name = player_name

        self.btn_confirm.label = t(gid, "confirm_btn2")
        self.btn_cancel.label  = t(gid, "cancel_btn")

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.danger, row=0)
    async def btn_confirm(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid
        uid = self.target_uid

        players = load_players(gid)
        players.pop(str(uid), None)
        save_players(gid, players)

        # DM the deceased player
        try:
            dm_embed = discord.Embed(
                description=t(gid, "player_death_dm"),
                color=0x2F2F2F,
            )
            await self.target_user.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

        await log_event(
            bot, gid, "admin",
            f"<@{ix.user.id}> flagged <@{uid}> ({self.player_name}) as deceased and deleted their character.",
        )

        embed = discord.Embed(
            description=t(gid, "player_deleted_msg", name=self.player_name),
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cancel(self, ix: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            description=t(self.gid, "panel_closed"),
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=None)


# ── Forum-based character creation ───────────────────────────────────────────

class ForumCreateModal1(discord.ui.Modal, title="Create Character (1/3) — Basic Info"):
    char_name  = discord.ui.TextInput(label="Name",       max_length=60)
    age        = discord.ui.TextInput(label="Age",         max_length=10)
    gender     = discord.ui.TextInput(label="Gender",      max_length=30)
    appearance = discord.ui.TextInput(
        label="Appearance",
        style=discord.TextStyle.paragraph,
        max_length=800,
    )
    image = discord.ui.TextInput(
        label="Image URL (optional)",
        required=False,
        max_length=300,
    )

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        self.char_name.label  = t(gid, "name_field")
        self.age.label        = t(gid, "age_field")
        self.gender.label     = t(gid, "gender_field")
        self.appearance.label = t(gid, "appearance_field")
        self.image.label      = t(gid, "image_field")

    async def on_submit(self, ix: discord.Interaction):
        step1 = {
            "name":       self.char_name.value.strip(),
            "age":        self.age.value.strip(),
            "gender":     self.gender.value.strip(),
            "appearance": self.appearance.value.strip(),
            "image":      (self.image.value or "").strip(),
        }
        await ix.response.send_modal(ForumCreateModal2(self.gid, step1))


class ForumCreateModal2(discord.ui.Modal, title="Create Character (2/3) — Backstory"):
    backstory = discord.ui.TextInput(
        label="Backstory",
        style=discord.TextStyle.paragraph,
        max_length=1500,
        required=False,
    )

    def __init__(self, gid: int, step1: dict):
        super().__init__()
        self.gid   = gid
        self.step1 = step1
        self.backstory.label = t(gid, "backstory_field")

    async def on_submit(self, ix: discord.Interaction):
        step2 = {**self.step1, "backstory": self.backstory.value.strip()}
        # Now choose faction/rank/bloodline via dropdowns
        gid        = self.gid
        uid        = ix.user.id
        cfg        = load_config(gid)
        bloodlines = get_available_bloodlines(gid, uid)
        view       = ForumCreateSelectsView(gid, uid, step2, cfg, bloodlines)
        embed = discord.Embed(
            title=t(gid, "profile_title"),
            description=t(gid, "register_step2"),
            color=EMBED_COLOR,
        )
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class ForumCreateSelectsView(discord.ui.View):
    def __init__(self, gid: int, uid: int, step2: dict, cfg: dict, bloodlines: list):
        super().__init__(timeout=300)
        self.gid        = gid
        self.uid        = uid
        self.step2      = step2
        self.cfg        = cfg
        self.bloodlines = bloodlines
        factions           = get_faction_names(gid)
        self.sel_faction   = factions[0] if factions else ""
        vis_ranks          = get_visible_ranks_for_faction(gid, self.sel_faction, uid)
        self.sel_rank      = vis_ranks[0] if vis_ranks else ""
        self.sel_bloodline = bloodlines[0] if bloodlines else ""
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid

        factions  = get_faction_names(gid)
        vis_ranks = get_visible_ranks_for_faction(gid, self.sel_faction, self.uid)

        faction_sel = discord.ui.Select(
            placeholder=t(gid, "select_faction"),
            options=select_options_from_list(factions, self.sel_faction),
            row=0,
        )
        faction_sel.callback = self._faction_cb
        self.add_item(faction_sel)

        rank_sel = discord.ui.Select(
            placeholder=t(gid, "select_rank"),
            options=select_options_from_list(vis_ranks, self.sel_rank),
            row=1,
        )
        rank_sel.callback = self._rank_cb
        self.add_item(rank_sel)

        bloodline_sel = discord.ui.Select(
            placeholder=t(gid, "select_bloodline"),
            options=select_options_from_list(self.bloodlines, self.sel_bloodline),
            row=2,
        )
        bloodline_sel.callback = self._bloodline_cb
        self.add_item(bloodline_sel)

        submit_btn = discord.ui.Button(
            label="📋 Submit for Review",
            style=discord.ButtonStyle.success,
            row=3,
        )
        submit_btn.callback = self._submit
        self.add_item(submit_btn)

    async def _faction_cb(self, ix: discord.Interaction):
        self.sel_faction = ix.data["values"][0]
        vis_ranks = get_visible_ranks_for_faction(self.gid, self.sel_faction, self.uid)
        self.sel_rank = vis_ranks[0] if vis_ranks else ""
        self._build()
        await ix.response.edit_message(view=self)

    async def _rank_cb(self, ix: discord.Interaction):
        self.sel_rank = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(view=self)

    async def _bloodline_cb(self, ix: discord.Interaction):
        self.sel_bloodline = ix.data["values"][0]
        self._build()
        await ix.response.edit_message(view=self)

    async def _submit(self, ix: discord.Interaction):
        gid = self.gid
        uid = ix.user.id
        cfg = load_config(gid)

        application = {
            **self.step2,
            "faction":    self.sel_faction,
            "rank":       self.sel_rank,
            "bloodline":  self.sel_bloodline,
            "submitter_id": str(uid),
            "submitted_at": time.time(),
            "status":     "pending",
        }

        # Create forum thread
        forum_thread_id = None
        forum_id = cfg.get("character_forum_id")
        if forum_id:
            try:
                forum = ix.guild.get_channel(int(forum_id))
                if isinstance(forum, discord.ForumChannel):
                    content = (
                        f"**Name:** {application['name']}\n"
                        f"**Age:** {application['age']}\n"
                        f"**Gender:** {application['gender']}\n"
                        f"**Bloodline:** {application['bloodline']}\n"
                        f"**Faction:** {application['faction']}\n"
                        f"**Rank:** {application['rank']}\n\n"
                        f"**Appearance:**\n{application['appearance']}\n\n"
                        f"**Backstory:**\n{application.get('backstory','')}"
                    )
                    app_embed = discord.Embed(
                        title=f"📋 {application['name']} — Character Application",
                        description=content[:4000],
                        color=0xF59E0B,
                    )
                    app_embed.set_footer(text=f"Applicant: {ix.user.display_name} ({uid})")
                    if application.get("image") and is_url(application["image"]):
                        app_embed.set_thumbnail(url=application["image"])
                    thread, _ = await forum.create_thread(
                        name=f"[PENDING] {application['name']} — {ix.user.display_name}",
                        content=f"<@{uid}> submitted a character application. Awaiting admin review.",
                        embed=app_embed,
                    )
                    forum_thread_id = thread.id
                    application["forum_thread_id"] = forum_thread_id
            except Exception:
                pass

        # Save pending
        pending = _load_pending(gid)
        pending[str(uid)] = application
        _save_pending(gid, pending)

        # Notify admin review channel
        review_ch_id = cfg.get("admin_review_channel_id")
        if review_ch_id:
            try:
                review_ch = ix.guild.get_channel(int(review_ch_id))
                if review_ch:
                    rev_embed = discord.Embed(
                        title=f"📋 New Application: {application['name']}",
                        description=(
                            f"**Player:** <@{uid}>\n"
                            f"**Faction:** {application['faction']}\n"
                            f"**Bloodline:** {application['bloodline']}"
                        ),
                        color=0xF59E0B,
                    )
                    if forum_thread_id:
                        rev_embed.add_field(name="Forum", value=f"<#{forum_thread_id}>", inline=True)
                    await review_ch.send(
                        embed=rev_embed,
                        view=ForumAdminReviewView(gid, str(uid)),
                    )
            except Exception:
                pass

        await ix.response.edit_message(
            embed=discord.Embed(
                title="✅ Application Submitted!",
                description=(
                    f"Your character **{application['name']}** has been submitted for review.\n"
                    "You'll be notified via DM when approved."
                    + (f"\nForum thread: <#{forum_thread_id}>" if forum_thread_id else "")
                ),
                color=discord.Color.green(),
            ),
            view=None,
        )


class ForumAdminReviewView(discord.ui.View):
    def __init__(self, gid: int, uid_key: str):
        super().__init__(timeout=None)
        self.gid     = gid
        self.uid_key = uid_key

    @discord.ui.button(label="✅ Approve", style=discord.ButtonStyle.success, row=0)
    async def btn_approve(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("Admin only.", ephemeral=True)
            return
        gid     = self.gid
        pending = _load_pending(gid)
        app     = pending.get(self.uid_key)
        if not app:
            await ix.response.send_message("Application not found (may already be processed).", ephemeral=True)
            return

        uid = int(self.uid_key)
        cfg = load_config(gid)

        # Build player record
        player = {
            "name":             app.get("name", ""),
            "age":              app.get("age", ""),
            "gender":           app.get("gender", ""),
            "appearance":       app.get("appearance", ""),
            "image":            app.get("image", ""),
            "backstory":        app.get("backstory", ""),
            "faction":          app.get("faction", ""),
            "rank":             app.get("rank", ""),
            "bloodline":        app.get("bloodline", ""),
            "shifter":          "None",
            "inventory":        {},
            "titan_powers":     [],
            "stamina":          100,
            "max_stamina":      100,
            "ability_cooldowns":{},
            "transformed":      False,
            "deceased":         False,
        }
        players = load_players(gid)
        players[str(uid)] = player
        save_players(gid, players)

        # Remove from pending
        del pending[self.uid_key]
        _save_pending(gid, pending)

        # Assign Discord roles
        member = ix.guild.get_member(uid)
        if member:
            try:
                await assign_roles(member, player, cfg)
            except Exception:
                pass

        # Rename forum thread
        thread_id = app.get("forum_thread_id")
        if thread_id:
            try:
                thread = ix.guild.get_thread(int(thread_id))
                if thread:
                    await thread.edit(name=thread.name.replace("[PENDING]", "[APPROVED]", 1))
            except Exception:
                pass

        # DM user
        try:
            if member:
                dm_embed = discord.Embed(
                    title="🎉 Character Approved!",
                    description=f"Your character **{app.get('name','?')}** has been approved!\nUse `/profile` to view it.",
                    color=discord.Color.green(),
                )
                await member.send(embed=dm_embed)
        except Exception:
            pass

        await log_event(bot, gid, "admin", f"<@{ix.user.id}> approved character {app.get('name','?')} for <@{uid}>")

        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"✅ Approved character **{app.get('name','?')}** for <@{uid}>",
                color=discord.Color.green(),
            ),
            view=None,
        )

    @discord.ui.button(label="❌ Decline", style=discord.ButtonStyle.danger, row=0)
    async def btn_decline(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("Admin only.", ephemeral=True)
            return
        await ix.response.send_modal(ForumDeclineModal(self.gid, self.uid_key))

    @discord.ui.button(label="✏️ Edit", style=discord.ButtonStyle.secondary, row=0)
    async def btn_edit(self, ix: discord.Interaction, _: discord.ui.Button):
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("Admin only.", ephemeral=True)
            return
        pending = _load_pending(self.gid)
        app     = pending.get(self.uid_key)
        if not app:
            await ix.response.send_message("Application not found.", ephemeral=True)
            return
        await ix.response.send_modal(ForumAdminEditModal(self.gid, self.uid_key, app))


class ForumDeclineModal(discord.ui.Modal, title="Decline Reason"):
    reason = discord.ui.TextInput(
        label="Reason (sent to player via DM)",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=False,
    )

    def __init__(self, gid: int, uid_key: str):
        super().__init__()
        self.gid     = gid
        self.uid_key = uid_key

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_pending(self.gid)
        app     = pending.get(self.uid_key, {})
        uid     = int(self.uid_key)

        try:
            member = ix.guild.get_member(uid)
            if member:
                dm_embed = discord.Embed(
                    title="❌ Character Application Declined",
                    description=(
                        f"Your application for **{app.get('name','?')}** was declined.\n"
                        + (f"**Reason:** {self.reason.value}" if self.reason.value else "")
                    ),
                    color=discord.Color.red(),
                )
                await member.send(embed=dm_embed)
        except Exception:
            pass

        # Archive forum thread
        thread_id = app.get("forum_thread_id")
        if thread_id:
            try:
                thread = ix.guild.get_thread(int(thread_id))
                if thread:
                    await thread.edit(name=thread.name.replace("[PENDING]", "[DECLINED]", 1))
                    await thread.edit(archived=True)
            except Exception:
                pass

        pending.pop(self.uid_key, None)
        _save_pending(self.gid, pending)
        await ix.response.send_message(
            embed=discord.Embed(description="❌ Application declined.", color=discord.Color.red()),
            ephemeral=True,
        )


class ForumAdminEditModal(discord.ui.Modal, title="Edit Application"):
    name_f   = discord.ui.TextInput(label="Name",      max_length=60)
    faction_f = discord.ui.TextInput(label="Faction",  max_length=60)
    rank_f   = discord.ui.TextInput(label="Rank",      max_length=60)
    blood_f  = discord.ui.TextInput(label="Bloodline", max_length=60)

    def __init__(self, gid: int, uid_key: str, app: dict):
        super().__init__()
        self.gid     = gid
        self.uid_key = uid_key
        self.name_f.default    = app.get("name", "")
        self.faction_f.default = app.get("faction", "")
        self.rank_f.default    = app.get("rank", "")
        self.blood_f.default   = app.get("bloodline", "")

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_pending(self.gid)
        app     = pending.get(self.uid_key, {})
        app["name"]      = self.name_f.value.strip()
        app["faction"]   = self.faction_f.value.strip()
        app["rank"]      = self.rank_f.value.strip()
        app["bloodline"] = self.blood_f.value.strip()
        pending[self.uid_key] = app
        _save_pending(self.gid, pending)
        await ix.response.send_message(
            embed=discord.Embed(description="✅ Application updated.", color=EMBED_COLOR),
            ephemeral=True,
        )


# ── Unregistered View ─────────────────────────────────────────────────────────

class UnregisteredView(discord.ui.View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.gid = guild_id
        self.btn_register.label = t(guild_id, "register_btn")

        # Show forum creation button only if forum is configured
        cfg = load_config(guild_id)
        if not cfg.get("character_forum_id"):
            self.remove_item(self.btn_forum_register)

    @discord.ui.button(label="Register Character", style=discord.ButtonStyle.green, row=0)
    async def btn_register(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid

        # Check creation role gate before opening modal
        missing_role = _check_creation_role(ix)
        if missing_role:
            embed = discord.Embed(
                description=t(gid, "no_creation_role", role=missing_role),
                color=0xFF0000,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        await ix.response.send_modal(RegisterModal(gid))

    @discord.ui.button(label="📋 Apply via Forum", style=discord.ButtonStyle.primary, row=0)
    async def btn_forum_register(self, ix: discord.Interaction, button: discord.ui.Button):
        gid = self.gid

        missing_role = _check_creation_role(ix)
        if missing_role:
            embed = discord.Embed(
                description=t(gid, "no_creation_role", role=missing_role),
                color=0xFF0000,
            )
            await ix.response.send_message(embed=embed, ephemeral=True)
            return

        # Check already pending
        pending = _load_pending(gid)
        if str(ix.user.id) in pending:
            await ix.response.send_message(
                embed=discord.Embed(
                    description="📋 Your application is already pending admin review.",
                    color=0xF59E0B,
                ),
                ephemeral=True,
            )
            return

        await ix.response.send_modal(ForumCreateModal1(gid))


# ── /profile slash command ────────────────────────────────────────────────────

@bot.tree.command(
    name="profile",
    description="View or create your character profile",
    description_localizations={"th": "ดูหรือสร้างโปรไฟล์ตัวละครของคุณ"},
)
async def profile_cmd(ix: discord.Interaction):
    gid    = ix.guild_id
    uid    = ix.user.id
    player = load_players(gid).get(str(uid))

    if not player:
        # Check if they have a pending forum application
        pending = _load_pending(gid)
        if str(uid) in pending:
            await ix.response.send_message(
                embed=discord.Embed(
                    title="📋 Application Pending",
                    description=(
                        "Your character application is awaiting admin review.\n"
                        "You'll be notified via DM when a decision is made."
                    ),
                    color=0xF59E0B,
                ),
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=t(gid, "profile_title"),
            description=t(gid, "not_registered"),
            color=EMBED_COLOR,
        )
        view = UnregisteredView(gid)
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)
    else:
        is_admin = (
            ix.user.guild_permissions.administrator
            if ix.guild
            else False
        )
        embed = _profile_embed(player, ix.user.display_name, gid)
        view  = ProfileView(uid, gid, ix.user.display_name, is_admin=is_admin)
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)
