"""Profile command — character creation with forum-based admin approval, embed UI."""
import asyncio, time, uuid, json, os, datetime
import discord
from discord import app_commands

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_players, save_players, load_config, save_config, load_items,
    select_options_from_list, get_available_bloodlines,
    has_shifter_access, assign_roles, remove_old_roles,
    format_profile_text, cv2_dm, is_url,
    get_faction_names, get_visible_ranks_for_faction, get_faction_emblem,
    log_event,
)
from pathlib import Path

DATA_DIR = Path("data")

# ── Pending character applications ────────────────────────────────────────────

def _pending_path(gid: int) -> Path:
    return DATA_DIR / f"aot_char_pending_{gid}.json"

def _load_pending(gid: int) -> dict:
    try:
        return json.loads(_pending_path(gid).read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_pending(gid: int, d: dict):
    DATA_DIR.mkdir(exist_ok=True)
    _pending_path(gid).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Embed builders ─────────────────────────────────────────────────────────────

def _profile_embed(player: dict, display_name: str, gid: int, uid: int) -> discord.Embed:
    name = player.get("name") or display_name
    faction = player.get("faction", "—")
    rank = player.get("rank", "—")
    bloodline = player.get("bloodline", "—")
    age = player.get("age", "—")
    gender = player.get("gender", "—")
    appearance = player.get("appearance", "")
    image = player.get("image", "").strip()
    balance = player.get("balance", 0)
    cfg = load_config(gid)
    currency = cfg.get("currency_name", "Coins")

    embed = discord.Embed(
        title=name,
        description=appearance[:600] if appearance else "_No appearance set._",
        color=0x2f3136,
    )
    embed.set_author(name=display_name)
    if image and is_url(image):
        embed.set_image(url=image)
    emblem = get_faction_emblem(gid, faction)
    if emblem:
        embed.set_thumbnail(url=emblem)

    embed.add_field(name="Faction", value=faction, inline=True)
    embed.add_field(name="Rank", value=rank, inline=True)
    embed.add_field(name="Bloodline", value=bloodline, inline=True)
    embed.add_field(name="Age", value=age, inline=True)
    embed.add_field(name="Gender", value=gender, inline=True)
    embed.add_field(name=currency, value=f"{balance:,}", inline=True)

    titan_powers = player.get("titan_powers", [])
    if titan_powers:
        titans = ", ".join(p.get("titan","?") for p in titan_powers)
        embed.add_field(name="Titan Powers", value=titans, inline=False)

    if player.get("deceased"):
        embed.color = 0x7f8c8d
        embed.add_field(name="Status", value="**DECEASED**", inline=False)

    embed.set_footer(text=f"ID: {uid}")
    return embed


def _char_review_embed(pid: str, d: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Character Application — {d.get('name','?')}",
        color=0xf39c12,
    )
    embed.set_author(name=f"{d.get('username','?')}  (ID: {d.get('uid','?')})")
    img = d.get("image", "")
    if img and is_url(img):
        embed.set_thumbnail(url=img)
    embed.add_field(name="Name", value=d.get("name","—"), inline=True)
    embed.add_field(name="Age", value=d.get("age","—"), inline=True)
    embed.add_field(name="Gender", value=d.get("gender","—"), inline=True)
    embed.add_field(name="Faction", value=d.get("faction","—"), inline=True)
    embed.add_field(name="Rank", value=d.get("rank","—"), inline=True)
    embed.add_field(name="Bloodline", value=d.get("bloodline","—"), inline=True)
    embed.add_field(name="Appearance", value=d.get("appearance","—")[:1024], inline=False)
    embed.set_footer(text=f"ID: {pid} · {d.get('submitted_at','?')}")
    return embed


# ── Admin review view ─────────────────────────────────────────────────────────

class AOTCharReviewView(discord.ui.View):
    def __init__(self, pid: str, applicant_uid: str):
        super().__init__(timeout=None)
        self.pid = pid
        self.applicant_uid = applicant_uid

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if not ix.user.guild_permissions.administrator:
            await ix.response.send_message("Admin only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, emoji="✅")
    async def btn_approve(self, ix: discord.Interaction, _b):
        gid = ix.guild.id
        pending = _load_pending(gid)
        d = pending.get(self.pid)
        if not d:
            await ix.response.send_message("Application not found.", ephemeral=True)
            return
        uid_str = d["uid"]
        players = load_players(gid)
        cfg = load_config(gid)
        old = players.get(uid_str, {})
        player = {
            "name":       d.get("name", ""),
            "age":        d.get("age", ""),
            "gender":     d.get("gender", ""),
            "appearance": d.get("appearance", ""),
            "image":      d.get("image", ""),
            "faction":    d.get("faction", ""),
            "rank":       d.get("rank", ""),
            "bloodline":  d.get("bloodline", ""),
            "shifter":          old.get("shifter", "None"),
            "inventory":        old.get("inventory", {}),
            "titan_powers":     old.get("titan_powers", []),
            "stamina":          old.get("stamina", 100),
            "max_stamina":      old.get("max_stamina", 100),
            "ability_cooldowns": old.get("ability_cooldowns", {}),
            "transformed": False,
            "deceased":    old.get("deceased", False),
            "balance":     old.get("balance", 0),
        }
        players[uid_str] = player
        save_players(gid, players)
        member = ix.guild.get_member(int(uid_str))
        if member:
            if old:
                await remove_old_roles(member, old, cfg)
            await assign_roles(member, player, cfg)
        pending[self.pid]["status"] = "approved"
        _save_pending(gid, pending)

        embed = _char_review_embed(self.pid, d)
        embed.color = discord.Color.green()
        embed.set_footer(text=f"Approved by {ix.user.display_name}")
        await ix.response.edit_message(embed=embed, view=None)
        try:
            if isinstance(ix.channel, discord.Thread):
                await ix.channel.edit(archived=True, locked=True)
        except Exception:
            pass
        try:
            user = await bot.fetch_user(int(uid_str))
            await user.send(embed=discord.Embed(
                title="Your character has been approved!",
                description="Welcome! Use `/profile` to view your character.",
                color=discord.Color.green(),
            ))
        except Exception:
            pass
        try:
            await log_event(bot, gid, "profile", f"<@{uid_str}> character approved by {ix.user.display_name}")
        except Exception:
            pass

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, emoji="❌")
    async def btn_decline(self, ix: discord.Interaction, _b):
        gid = ix.guild.id
        pending = _load_pending(gid)
        if self.pid not in pending:
            await ix.response.send_message("Not found.", ephemeral=True)
            return
        await ix.response.send_modal(AOTCharDeclineModal(self.pid, self.applicant_uid, gid))

    @discord.ui.button(label="Request Revision", style=discord.ButtonStyle.primary, emoji="✏️")
    async def btn_edit(self, ix: discord.Interaction, _b):
        gid = ix.guild.id
        pending = _load_pending(gid)
        if self.pid not in pending:
            await ix.response.send_message("Not found.", ephemeral=True)
            return
        await ix.response.send_modal(AOTCharEditReasonModal(self.pid, self.applicant_uid, gid))


class AOTCharDeclineModal(discord.ui.Modal, title="Decline Reason"):
    f_reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, pid: str, uid: str, gid: int):
        super().__init__()
        self.pid = pid; self.uid = uid; self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_pending(self.gid)
        if self.pid in pending:
            pending[self.pid]["status"] = "declined"
            _save_pending(self.gid, pending)
        d = pending.get(self.pid, {})
        embed = _char_review_embed(self.pid, d)
        embed.color = discord.Color.red()
        embed.set_footer(text=f"Declined by {ix.user.display_name}")
        await ix.response.edit_message(embed=embed, view=None)
        try:
            if isinstance(ix.channel, discord.Thread):
                await ix.channel.edit(archived=True, locked=True)
        except Exception:
            pass
        try:
            user = await bot.fetch_user(int(self.uid))
            await user.send(embed=discord.Embed(
                title="Character application declined",
                description=f"**Reason:** {self.f_reason.value.strip()}\nUse `/profile` to revise and resubmit.",
                color=discord.Color.red(),
            ))
        except Exception:
            pass


class AOTCharEditReasonModal(discord.ui.Modal, title="Request Revision"):
    f_reason = discord.ui.TextInput(label="What needs to change", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, pid: str, uid: str, gid: int):
        super().__init__()
        self.pid = pid; self.uid = uid; self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        pending = _load_pending(self.gid)
        if self.pid in pending:
            pending[self.pid]["status"] = "needs_revision"
            pending[self.pid]["revision_reason"] = self.f_reason.value.strip()
            _save_pending(self.gid, pending)
        d = pending.get(self.pid, {})
        embed = _char_review_embed(self.pid, d)
        embed.color = discord.Color.orange()
        embed.add_field(name="Revision Required", value=self.f_reason.value.strip(), inline=False)
        embed.set_footer(text=f"Needs revision — requested by {ix.user.display_name}")
        await ix.response.edit_message(embed=embed, view=None)
        try:
            user = await bot.fetch_user(int(self.uid))
            await user.send(embed=discord.Embed(
                title="Your character needs revision",
                description=f"**Required changes:** {self.f_reason.value.strip()}\nUse `/profile` to resubmit.",
                color=discord.Color.orange(),
            ))
        except Exception:
            pass


async def _post_char_review(guild: discord.Guild, pid: str, d: dict):
    gid = guild.id
    cfg = load_config(gid)
    ch_id = cfg.get("char_review_channel_id")
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if not ch:
        return
    embed = _char_review_embed(pid, d)
    view = AOTCharReviewView(pid, d["uid"])
    if isinstance(ch, discord.ForumChannel):
        thread, msg = await ch.create_thread(
            name=f"[App] {d.get('name','?')} — {d.get('username','?')}",
            embed=embed,
            view=view,
        )
        msg_id = msg.id
    else:
        msg = await ch.send(embed=embed, view=view)
        msg_id = msg.id
    pending = _load_pending(gid)
    if pid in pending:
        pending[pid]["review_message_id"] = msg_id
        _save_pending(gid, pending)


# ── Registration Step 1: Basic Info Modal ────────────────────────────────────

class RegisterModal(discord.ui.Modal, title="Create Character"):
    f_name       = discord.ui.TextInput(label="Character Name", max_length=60)
    f_age        = discord.ui.TextInput(label="Age", max_length=10)
    f_gender     = discord.ui.TextInput(label="Gender", max_length=30)
    f_appearance = discord.ui.TextInput(label="Appearance", style=discord.TextStyle.paragraph, max_length=500)
    f_image      = discord.ui.TextInput(label="Image URL (optional)", max_length=300, required=False)

    def __init__(self, guild_id: int, prefill: dict = None):
        super().__init__()
        self.guild_id = guild_id
        gid = guild_id
        self.f_name.label       = t(gid, "name_field")
        self.f_age.label        = t(gid, "age_field")
        self.f_gender.label     = t(gid, "gender_field")
        self.f_appearance.label = t(gid, "appearance_field")
        self.f_image.label      = t(gid, "image_field")
        if prefill:
            self.f_name.default       = prefill.get("name", "")[:60]
            self.f_age.default        = prefill.get("age", "")[:10]
            self.f_gender.default     = prefill.get("gender", "")[:30]
            self.f_appearance.default = prefill.get("appearance", "")[:500]
            self.f_image.default      = prefill.get("image", "")[:300]

    async def on_submit(self, ix: discord.Interaction):
        gid = self.guild_id
        uid = ix.user.id
        step1 = {
            "name":       self.f_name.value.strip(),
            "age":        self.f_age.value.strip(),
            "gender":     self.f_gender.value.strip(),
            "appearance": self.f_appearance.value.strip(),
            "image":      (self.f_image.value or "").strip(),
        }
        cfg        = load_config(gid)
        bloodlines = get_available_bloodlines(gid, uid)
        existing   = load_players(gid).get(str(uid), {})
        view = RegisterSelectsView(gid, uid, step1, cfg, bloodlines,
                                   existing_player=existing, is_edit=bool(existing))
        embed = discord.Embed(
            title=t(gid, "profile_title"),
            description=t(gid, "register_step2"),
            color=0x3498db,
        )
        await ix.response.edit_message(embed=embed, view=view)


# ── Step 2: Dropdowns (faction / rank / bloodline) ────────────────────────────

class RegisterSelectsView(discord.ui.View):
    def __init__(self, gid: int, uid: int, step1: dict, cfg: dict, bloodlines: list,
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
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        gid = self.gid
        factions  = get_faction_names(gid)
        vis_ranks = get_visible_ranks_for_faction(gid, self.sel_faction, self.uid)

        if factions:
            sel_faction = discord.ui.Select(
                placeholder=t(gid, "select_faction"),
                options=select_options_from_list(factions, self.sel_faction),
                row=0,
            )
            sel_faction.callback = self._faction_cb
            self.add_item(sel_faction)

        if vis_ranks:
            sel_rank = discord.ui.Select(
                placeholder=t(gid, "select_rank"),
                options=select_options_from_list(vis_ranks, self.sel_rank),
                row=1,
            )
            sel_rank.callback = self._rank_cb
            self.add_item(sel_rank)

        if self.bloodlines:
            sel_bl = discord.ui.Select(
                placeholder=t(gid, "select_bloodline"),
                options=select_options_from_list(self.bloodlines, self.sel_bloodline),
                row=2,
            )
            sel_bl.callback = self._bloodline_cb
            self.add_item(sel_bl)

        confirm = discord.ui.Button(
            label=t(gid, "confirm_btn"),
            style=discord.ButtonStyle.success,
            row=3,
        )
        confirm.callback = self._confirm
        self.add_item(confirm)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.id != self.uid:
            await ix.response.send_message("Not your menu.", ephemeral=True)
            return False
        return True

    async def _faction_cb(self, ix: discord.Interaction):
        self.sel_faction = ix.data["values"][0]
        vis_ranks = get_visible_ranks_for_faction(self.gid, self.sel_faction, self.uid)
        self.sel_rank = vis_ranks[0] if vis_ranks else ""
        self._rebuild()
        await ix.response.edit_message(view=self)

    async def _rank_cb(self, ix: discord.Interaction):
        self.sel_rank = ix.data["values"][0]
        self._rebuild()
        await ix.response.edit_message(view=self)

    async def _bloodline_cb(self, ix: discord.Interaction):
        self.sel_bloodline = ix.data["values"][0]
        self._rebuild()
        await ix.response.edit_message(view=self)

    async def _confirm(self, ix: discord.Interaction):
        gid, uid = self.gid, self.uid
        uid_str  = str(uid)
        existing = load_players(gid).get(uid_str, {})

        if self.is_edit and existing:
            # Direct edit — no approval needed
            players = load_players(gid)
            cfg = load_config(gid)
            old = players.get(uid_str, {})
            player = {
                **old,
                "name":       self.step1.get("name",""),
                "age":        self.step1.get("age",""),
                "gender":     self.step1.get("gender",""),
                "appearance": self.step1.get("appearance",""),
                "image":      self.step1.get("image",""),
                "faction":    self.sel_faction,
                "rank":       self.sel_rank,
                "bloodline":  self.sel_bloodline,
                "transformed": False,
            }
            players[uid_str] = player
            save_players(gid, players)
            member = ix.guild.get_member(uid)
            if member:
                await remove_old_roles(member, old, cfg)
                await assign_roles(member, player, cfg)
            embed = _profile_embed(player, ix.user.display_name, gid, uid)
            embed.set_footer(text="Character updated successfully.")
            await ix.response.edit_message(embed=embed, view=ProfileView(uid, gid, ix.user.display_name))
            await log_event(bot, gid, "profile", f"<@{uid}> updated their character")
            return

        # New character — send to pending review
        pending = _load_pending(gid)
        has_pending = any(
            p.get("uid") == uid_str and p.get("status") in ("pending", "needs_revision")
            for p in pending.values()
        )
        if has_pending:
            embed = discord.Embed(
                title="Application Pending",
                description="You already have a pending application. Please wait for admin review.",
                color=discord.Color.orange(),
            )
            await ix.response.edit_message(embed=embed, view=None)
            return

        pid = str(uuid.uuid4())[:8]
        data = {
            "uid":          uid_str,
            "username":     ix.user.display_name,
            "submitted_at": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
            "status":       "pending",
            "name":         self.step1.get("name", ""),
            "age":          self.step1.get("age", ""),
            "gender":       self.step1.get("gender", ""),
            "appearance":   self.step1.get("appearance", ""),
            "image":        self.step1.get("image", ""),
            "faction":      self.sel_faction,
            "rank":         self.sel_rank,
            "bloodline":    self.sel_bloodline,
        }
        pending[pid] = data
        _save_pending(gid, pending)

        embed = discord.Embed(
            title="Application Submitted!",
            description="Your character application has been sent for admin review.\nYou'll receive a DM when it's processed.",
            color=discord.Color.blurple(),
        )
        await ix.response.edit_message(embed=embed, view=None)
        if ix.guild:
            await _post_char_review(ix.guild, pid, data)
        await log_event(bot, gid, "profile", f"<@{uid}> submitted a character application")


# ── Profile view (tabs) ───────────────────────────────────────────────────────

_INV_PER_PAGE  = 8
_SKILLS_LABEL  = "Inventory"


class ProfileView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int, display_name: str = "", is_admin_view: bool = False):
        super().__init__(timeout=300)
        self.uid          = user_id
        self.gid          = guild_id
        self.display_name = display_name
        self.is_admin_view = is_admin_view
        self._build()

    def _build(self):
        self.clear_items()
        gid = self.gid
        btn_inv = discord.ui.Button(
            label=t(gid, "inventory_btn"), style=discord.ButtonStyle.secondary, row=0
        )
        btn_inv.callback = self._inventory_tab
        btn_bs = discord.ui.Button(
            label=t(gid, "backstory_tab"), style=discord.ButtonStyle.secondary, row=0
        )
        btn_bs.callback = self._backstory_tab
        btn_jn = discord.ui.Button(
            label=t(gid, "journal_tab"), style=discord.ButtonStyle.secondary, row=0
        )
        btn_jn.callback = self._journal_tab
        self.add_item(btn_inv)
        self.add_item(btn_bs)
        self.add_item(btn_jn)

        if not self.is_admin_view:
            btn_edit = discord.ui.Button(
                label=t(gid, "edit_btn"), style=discord.ButtonStyle.primary, row=1
            )
            btn_edit.callback = self._edit
            self.add_item(btn_edit)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if self.is_admin_view:
            return ix.user.guild_permissions.administrator
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return False
        return True

    async def _inventory_tab(self, ix: discord.Interaction):
        from aot_items import InventoryView
        await ix.response.edit_message(
            embed=discord.Embed(title="Inventory", color=0x2f3136),
            view=InventoryView(self.uid, self.gid, self),
        )

    async def _backstory_tab(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=_backstory_embed(self.uid, self.gid),
            view=BackstoryView(self.uid, self.gid, self),
        )

    async def _journal_tab(self, ix: discord.Interaction):
        view = JournalView(self.uid, self.gid, self)
        await ix.response.edit_message(
            embed=_journal_embed(self.uid, self.gid, 0),
            view=view,
        )

    async def _edit(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(RegisterModal(self.gid, prefill=player))


# ── Backstory ─────────────────────────────────────────────────────────────────

def _backstory_embed(uid: int, gid: int) -> discord.Embed:
    player    = load_players(gid).get(str(uid), {})
    backstory = player.get("backstory", "").strip()
    embed = discord.Embed(
        title=t(gid, "backstory_tab"),
        description=backstory or t(gid, "backstory_empty"),
        color=0x3d3d3d,
    )
    return embed


class BackstoryView(discord.ui.View):
    def __init__(self, uid: int, gid: int, parent):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.parent = parent

        btn_bk   = discord.ui.Button(label=t(gid,"back_btn"),         style=discord.ButtonStyle.secondary, row=0)
        btn_edit = discord.ui.Button(label=t(gid,"edit_backstory_btn"), style=discord.ButtonStyle.primary,   row=0)
        btn_bk.callback   = self._back
        btn_edit.callback = self._edit
        self.add_item(btn_bk)
        self.add_item(btn_edit)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return False
        return True

    async def _back(self, ix: discord.Interaction):
        player = load_players(self.gid).get(str(self.uid), {})
        embed = _profile_embed(player, self.parent.display_name, self.gid, self.uid)
        await ix.response.edit_message(embed=embed, view=self.parent)

    async def _edit(self, ix: discord.Interaction):
        player = load_players(self.gid).get(str(self.uid), {})
        await ix.response.send_modal(BackstoryEditModal(self.uid, self.gid, player.get("backstory",""), self))


class BackstoryEditModal(discord.ui.Modal, title="Edit Backstory"):
    f_text = discord.ui.TextInput(label="Backstory", style=discord.TextStyle.paragraph,
                                   max_length=2000, required=False)

    def __init__(self, uid: int, gid: int, current: str, parent):
        super().__init__()
        self.uid = uid; self.gid = gid; self.parent = parent
        self.f_text.label   = t(gid, "backstory_field")
        self.f_text.default = current[:2000]

    async def on_submit(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["backstory"] = self.f_text.value.strip()
        players[str(self.uid)] = player
        save_players(self.gid, players)
        await log_event(bot, self.gid, "profile", f"<@{self.uid}> updated backstory")
        embed = _backstory_embed(self.uid, self.gid)
        await ix.response.edit_message(embed=embed, view=self.parent)


# ── Journal ───────────────────────────────────────────────────────────────────

_JOURNAL_PER_PAGE = 3


def _journal_embed(uid: int, gid: int, page: int) -> discord.Embed:
    player  = load_players(gid).get(str(uid), {})
    entries = player.get("journal", [])
    total_pages = max(1, (len(entries) + _JOURNAL_PER_PAGE - 1) // _JOURNAL_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = list(reversed(entries))[page * _JOURNAL_PER_PAGE:(page + 1) * _JOURNAL_PER_PAGE]

    embed = discord.Embed(
        title=t(gid, "journal_tab"),
        description=f"Page {page+1}/{total_pages}",
        color=0x2c3e50,
    )
    if not chunk:
        embed.description = t(gid, "journal_empty")
        return embed
    for e in chunk:
        vis = "Public" if e.get("public") else "Private"
        ts  = time.strftime("%Y-%m-%d", time.localtime(e.get("ts", 0)))
        embed.add_field(
            name=f"{ts} [{vis}]",
            value=e.get("content","")[:512],
            inline=False,
        )
    return embed


class JournalView(discord.ui.View):
    def __init__(self, uid: int, gid: int, parent, page: int = 0):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.parent = parent; self.page = page
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        gid = self.gid
        player  = load_players(gid).get(str(self.uid), {})
        entries = player.get("journal", [])
        total_pages = max(1, (len(entries) + _JOURNAL_PER_PAGE - 1) // _JOURNAL_PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))

        btn_bk  = discord.ui.Button(label=t(gid,"back_btn"),     style=discord.ButtonStyle.secondary, row=0)
        btn_add = discord.ui.Button(label=t(gid,"add_journal_btn"), style=discord.ButtonStyle.success, row=0)
        btn_bk.callback  = self._back
        btn_add.callback = self._add
        self.add_item(btn_bk)
        self.add_item(btn_add)

        if total_pages > 1:
            btn_prev = discord.ui.Button(
                label=t(gid,"prev_btn"), style=discord.ButtonStyle.secondary,
                row=1, disabled=(self.page == 0)
            )
            btn_next = discord.ui.Button(
                label=t(gid,"next_btn"), style=discord.ButtonStyle.secondary,
                row=1, disabled=(self.page >= total_pages - 1)
            )
            btn_prev.callback = self._prev
            btn_next.callback = self._next
            self.add_item(btn_prev)
            self.add_item(btn_next)

        chunk = list(reversed(entries))[self.page * _JOURNAL_PER_PAGE:(self.page+1)*_JOURNAL_PER_PAGE]
        if chunk:
            opts = [
                discord.SelectOption(
                    label=time.strftime("%Y-%m-%d", time.localtime(e.get("ts",0)))[:100],
                    value=e["id"],
                    description=("Public" if e.get("public") else "Private"),
                )
                for e in chunk if "id" in e
            ]
            if opts:
                sel = discord.ui.Select(placeholder="Manage entry...", options=opts, row=2)
                sel.callback = self._manage_entry
                self.add_item(sel)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return False
        return True

    async def _back(self, ix: discord.Interaction):
        player = load_players(self.gid).get(str(self.uid), {})
        embed = _profile_embed(player, self.parent.display_name, self.gid, self.uid)
        await ix.response.edit_message(embed=embed, view=self.parent)

    async def _add(self, ix: discord.Interaction):
        await ix.response.send_modal(JournalAddModal(self.uid, self.gid, self))

    async def _manage_entry(self, ix: discord.Interaction):
        entry_id = ix.data["values"][0]
        await ix.response.edit_message(
            embed=discord.Embed(title="Manage Entry", color=0x2c3e50),
            view=JournalEntryManageView(self.uid, self.gid, entry_id, self),
        )

    async def _prev(self, ix: discord.Interaction):
        self.page -= 1; self._rebuild()
        await ix.response.edit_message(embed=_journal_embed(self.uid, self.gid, self.page), view=self)

    async def _next(self, ix: discord.Interaction):
        self.page += 1; self._rebuild()
        await ix.response.edit_message(embed=_journal_embed(self.uid, self.gid, self.page), view=self)


class JournalAddModal(discord.ui.Modal, title="Add Journal Entry"):
    f_content = discord.ui.TextInput(label="Entry", style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, uid: int, gid: int, parent):
        super().__init__()
        self.uid = uid; self.gid = gid; self.parent = parent
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
        self.parent.page = 0
        self.parent._rebuild()
        await ix.response.edit_message(
            embed=_journal_embed(self.uid, self.gid, 0),
            view=self.parent,
        )


class JournalEntryManageView(discord.ui.View):
    def __init__(self, uid: int, gid: int, entry_id: str, parent):
        super().__init__(timeout=300)
        self.uid = uid; self.gid = gid; self.entry_id = entry_id; self.parent = parent
        players = load_players(gid)
        player  = players.get(str(uid), {})
        entry   = next((e for e in player.get("journal", []) if e.get("id") == entry_id), {})
        is_pub  = entry.get("public", False)

        btn_bk  = discord.ui.Button(label=t(gid,"back_btn"),       style=discord.ButtonStyle.secondary, row=0)
        btn_tg  = discord.ui.Button(
            label=t(gid,"journal_private_btn") if is_pub else t(gid,"journal_public_btn"),
            style=discord.ButtonStyle.secondary, row=0,
        )
        btn_del = discord.ui.Button(label=t(gid,"journal_delete_btn"), style=discord.ButtonStyle.danger, row=0)
        btn_bk.callback  = self._back
        btn_tg.callback  = self._toggle
        btn_del.callback = self._delete
        self.add_item(btn_bk)
        self.add_item(btn_tg)
        self.add_item(btn_del)

    async def interaction_check(self, ix: discord.Interaction) -> bool:
        if ix.user.id != self.uid:
            await ix.response.send_message(t(self.gid, "not_your_profile"), ephemeral=True)
            return False
        return True

    async def _back(self, ix: discord.Interaction):
        self.parent._rebuild()
        await ix.response.edit_message(
            embed=_journal_embed(self.uid, self.gid, self.parent.page),
            view=self.parent,
        )

    async def _toggle(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        for e in player.get("journal", []):
            if e.get("id") == self.entry_id:
                e["public"] = not e.get("public", False)
                break
        save_players(self.gid, players)
        self.parent._rebuild()
        await ix.response.edit_message(
            embed=_journal_embed(self.uid, self.gid, self.parent.page),
            view=self.parent,
        )

    async def _delete(self, ix: discord.Interaction):
        players = load_players(self.gid)
        player  = players.get(str(self.uid), {})
        player["journal"] = [e for e in player.get("journal", []) if e.get("id") != self.entry_id]
        save_players(self.gid, players)
        self.parent.page = 0
        self.parent._rebuild()
        await ix.response.edit_message(
            embed=_journal_embed(self.uid, self.gid, 0),
            view=self.parent,
        )


# ── /profile command ──────────────────────────────────────────────────────────

@bot.tree.command(
    name="profile",
    description="View or create your character profile | ดูหรือสร้างโปรไฟล์ตัวละคร",
    guild=GUILD2_OBJ,
)
async def profile_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    gid = ix.guild_id
    uid = ix.user.id
    cfg = load_config(gid)

    # Check required creation role
    required_role_id = cfg.get("required_creation_role_id")
    player = load_players(gid).get(str(uid))

    if not player:
        # Check role requirement before allowing creation
        if required_role_id:
            member = ix.guild.get_member(uid)
            if member:
                has_role = any(r.id == int(required_role_id) for r in member.roles)
                if not has_role:
                    role_obj = ix.guild.get_role(int(required_role_id))
                    role_name = role_obj.name if role_obj else f"ID:{required_role_id}"
                    embed = discord.Embed(
                        title="Role Required",
                        description=f"You need the **{role_name}** role to create a character.",
                        color=discord.Color.red(),
                    )
                    await ix.response.send_message(embed=embed, ephemeral=True)
                    return

        # Check pending application
        pending = _load_pending(gid)
        my_pending = [p for p in pending.values()
                      if p.get("uid") == str(uid) and p.get("status") in ("pending", "needs_revision")]
        if my_pending:
            p = my_pending[0]
            status = p.get("status", "pending")
            if status == "needs_revision":
                reason = p.get("revision_reason","")
                embed = discord.Embed(
                    title="Application Needs Revision",
                    description=f"**Changes required:** {reason}\n\nPlease edit and resubmit.",
                    color=discord.Color.orange(),
                )
                btn_edit = discord.ui.Button(label="Edit & Resubmit", style=discord.ButtonStyle.primary)
                async def _resubmit(interaction: discord.Interaction):
                    await interaction.response.send_modal(RegisterModal(gid, prefill=p))
                btn_edit.callback = _resubmit
                view = discord.ui.View(timeout=300)
                view.add_item(btn_edit)
                await ix.response.send_message(embed=embed, view=view, ephemeral=True)
            else:
                embed = discord.Embed(
                    title="Application Pending",
                    description="Your character application is pending admin review. You'll receive a DM when it's processed.",
                    color=discord.Color.blurple(),
                )
                await ix.response.send_message(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=t(gid, "profile_title"),
            description=t(gid, "not_registered"),
            color=0x3498db,
        )
        btn = discord.ui.Button(label=t(gid, "register_btn"), style=discord.ButtonStyle.success)
        async def _start_register(interaction: discord.Interaction):
            await interaction.response.send_modal(RegisterModal(gid))
        btn.callback = _start_register
        view = discord.ui.View(timeout=300)
        view.add_item(btn)
        await ix.response.send_message(embed=embed, view=view, ephemeral=True)
    else:
        embed = _profile_embed(player, ix.user.display_name, gid, uid)
        await ix.response.send_message(embed=embed, view=ProfileView(uid, gid, ix.user.display_name), ephemeral=True)


# ── /view-profile — admin command ─────────────────────────────────────────────

@bot.tree.command(
    name="view-profile",
    description="[Admin] View another player's profile | ดูโปรไฟล์ผู้เล่นอื่น",
    guild=GUILD2_OBJ,
)
@app_commands.describe(member="The member whose profile you want to view")
async def view_profile_cmd(ix: discord.Interaction, member: discord.Member):
    if not ix.guild or ix.guild.id != GUILD2_ID:
        return
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    gid = ix.guild_id
    uid = member.id
    player = load_players(gid).get(str(uid))
    if not player:
        embed = discord.Embed(
            title="No Character",
            description=f"{member.mention} has no character.",
            color=discord.Color.red(),
        )
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    embed = _profile_embed(player, member.display_name, gid, uid)
    embed.set_footer(text=f"Admin view — {member.display_name} (ID: {uid})")
    await ix.response.send_message(
        embed=embed,
        view=ProfileView(uid, gid, member.display_name, is_admin_view=True),
        ephemeral=True,
    )
