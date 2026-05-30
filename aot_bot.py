"""
Attack on Titan Discord Bot
discord.py 2.x — slash commands (app_commands)
"""

import os
import sys
import json
import re
import asyncio
import subprocess
import tempfile
import shutil
from pathlib import Path


# ---------------------------------------------------------------------------
# Auto-install dependencies
# ---------------------------------------------------------------------------

def _ensure(*pkgs):
    for p in pkgs:
        mod = p.split(">=")[0].split("[")[0].replace("-", "_")
        try:
            __import__(mod)
        except ImportError:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", p, "--quiet"],
                check=False,
            )


_ensure("discord.py>=2.3")

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select, Modal, TextInput

# ---------------------------------------------------------------------------
# Constants / paths
# ---------------------------------------------------------------------------

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "roles": {"faction": {}, "rank": {}, "shifter": {}, "bloodline": {}},
    "factions": [
        "Survey Corps",
        "Military Police",
        "Garrison",
        "Stationary Guard",
        "Merchants",
        "Civilian",
    ],
    "ranks": ["Cadet", "Soldier", "Section Commander", "Commander", "General"],
    "shifters": [
        "None",
        "Attack Titan",
        "Armored Titan",
        "Colossal Titan",
        "Female Titan",
        "Beast Titan",
        "Jaw Titan",
        "Cart Titan",
        "War Hammer Titan",
        "Founding Titan",
    ],
    "bloodlines_common": ["Human", "Mixed Blood"],
    "bloodlines_special": ["Ackerman", "Royal Blood"],
    "special_access": {},
}

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------


def _load_json(path: Path, default):
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default() if callable(default) else default


def _save_json(path: Path, data):
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    shutil.move(str(tmp), str(path))


def players_path(guild_id: int) -> Path:
    return DATA_DIR / f"players_{guild_id}.json"


def config_path(guild_id: int) -> Path:
    return DATA_DIR / f"config_{guild_id}.json"


def items_path(guild_id: int) -> Path:
    return DATA_DIR / f"items_{guild_id}.json"


def load_players(guild_id: int) -> dict:
    return _load_json(players_path(guild_id), dict)


def save_players(guild_id: int, data: dict):
    _save_json(players_path(guild_id), data)


def load_config(guild_id: int) -> dict:
    cfg = _load_json(config_path(guild_id), dict)
    # Merge with defaults so new keys are always present
    merged = dict(DEFAULT_CONFIG)
    merged.update(cfg)
    # Ensure nested role dicts exist
    for rtype in ("faction", "rank", "shifter", "bloodline"):
        merged["roles"].setdefault(rtype, {})
    return merged


def save_config(guild_id: int, data: dict):
    _save_json(config_path(guild_id), data)


def load_items(guild_id: int) -> dict:
    return _load_json(items_path(guild_id), lambda: {"categories": {}, "category_order": [], "items": {}})


def save_items(guild_id: int, data: dict):
    _save_json(items_path(guild_id), data)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def slugify(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[^a-z0-9\s_]", "", name)
    name = re.sub(r"\s+", "_", name)
    return name


def is_emoji(text: str) -> bool:
    """Return True if text looks like a plain emoji (unicode or <:name:id>)."""
    if re.match(r"^<a?:[^:]+:\d+>$", text.strip()):
        return True
    # Rough check for unicode emoji: non-ASCII printable
    if text.strip() and not text.strip().startswith("http"):
        return True
    return False


def is_url(text: str) -> bool:
    return text.strip().startswith("http://") or text.strip().startswith("https://")


def format_profile_text(player: dict, display_name: str) -> str:
    lines = [
        "## 📋 Character Profile",
        f"-# {display_name}",
        "",
        f"**Name** — {player.get('name', '?')}",
        f"**Age** — {player.get('age', '?')}",
        f"**Gender** — {player.get('gender', '?')}",
        f"**Bloodline** — {player.get('bloodline', '?')}",
        f"**Shifter** — {player.get('shifter', '?')}",
        f"**Faction** — {player.get('faction', '?')}",
        f"**Rank** — {player.get('rank', '?')}",
        "",
        "**Appearance**",
        f"*{player.get('appearance', '?')}*",
    ]
    img = player.get("image", "").strip()
    if img:
        if is_url(img):
            lines.append(f"\n[Character Image]({img})")
        else:
            lines.append(f"\n{img}")
    return "\n".join(lines)


def format_inventory_text(player: dict, items_data: dict) -> str:
    inventory = player.get("inventory", {})
    categories = items_data.get("categories", {})
    cat_order = items_data.get("category_order", [])
    all_items = items_data.get("items", {})

    lines = ["## 🎒 Inventory", ""]

    if not inventory:
        lines.append("*Empty*")
        return "\n".join(lines)

    # Group by category
    cat_items: dict[str, list] = {}
    uncategorized = []
    for item_id, qty in inventory.items():
        if qty <= 0:
            continue
        item = all_items.get(item_id)
        if item is None:
            continue
        cat_id = item.get("category", "")
        if cat_id in categories:
            cat_items.setdefault(cat_id, []).append((item, qty))
        else:
            uncategorized.append((item, qty))

    shown_any = False
    ordered_cats = [c for c in cat_order if c in cat_items]
    for cat_id in ordered_cats:
        cat = categories[cat_id]
        emoji = cat.get("emoji", "📦")
        name = cat.get("name", cat_id)
        lines.append(f"**{emoji} {name}**")
        for item, qty in cat_items[cat_id]:
            item_emoji = item.get("emoji", "📦")
            item_name = item.get("name", "?")
            lines.append(f"  {item_emoji} {item_name} × {qty}")
        lines.append("")
        shown_any = True

    if uncategorized:
        lines.append("**📦 Other**")
        for item, qty in uncategorized:
            item_emoji = item.get("emoji", "📦")
            item_name = item.get("name", "?")
            lines.append(f"  {item_emoji} {item_name} × {qty}")
        lines.append("")
        shown_any = True

    if not shown_any:
        lines.append("*Empty*")

    return "\n".join(lines)


def get_available_bloodlines(guild_id: int, user_id: int) -> list[str]:
    cfg = load_config(guild_id)
    bloodlines = list(cfg.get("bloodlines_common", []))
    special_access = cfg.get("special_access", {})
    user_granted = special_access.get(str(user_id), [])
    for bl in cfg.get("bloodlines_special", []):
        if bl in user_granted:
            bloodlines.append(bl)
    return bloodlines


def select_options_from_list(items: list[str], current: str = None) -> list[discord.SelectOption]:
    if not items:
        return [discord.SelectOption(label="No options available", value="__none__")]
    return [
        discord.SelectOption(label=s, value=s, default=(s == current))
        for s in items
    ]


# ---------------------------------------------------------------------------
# Role assignment helpers
# ---------------------------------------------------------------------------


async def assign_roles(member: discord.Member, player: dict, cfg: dict):
    """Assign discord roles based on player profile."""
    roles_cfg = cfg.get("roles", {})
    guild = member.guild
    roles_to_add = []
    for field in ("faction", "rank", "shifter", "bloodline"):
        value = player.get(field)
        if not value or value == "None":
            continue
        role_id_str = roles_cfg.get(field, {}).get(value)
        if role_id_str:
            role = guild.get_role(int(role_id_str))
            if role:
                roles_to_add.append(role)
    if roles_to_add:
        try:
            await member.add_roles(*roles_to_add, reason="AoT profile assignment")
        except discord.Forbidden:
            pass


async def remove_old_roles(member: discord.Member, old_player: dict, cfg: dict):
    """Remove discord roles from previous player profile."""
    roles_cfg = cfg.get("roles", {})
    guild = member.guild
    roles_to_remove = []
    for field in ("faction", "rank", "shifter", "bloodline"):
        value = old_player.get(field)
        if not value or value == "None":
            continue
        role_id_str = roles_cfg.get(field, {}).get(value)
        if role_id_str:
            role = guild.get_role(int(role_id_str))
            if role and role in member.roles:
                roles_to_remove.append(role)
    if roles_to_remove:
        try:
            await member.remove_roles(*roles_to_remove, reason="AoT profile update")
        except discord.Forbidden:
            pass


# ---------------------------------------------------------------------------
# Bot setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.members = True
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------------------------------------------------------
# /profile — Views and Modals
# ---------------------------------------------------------------------------


class RegisterModal(Modal, title="Register Your Character"):
    char_name = TextInput(label="Character Name", max_length=60, required=True)
    age = TextInput(label="Age", max_length=10, required=True)
    gender = TextInput(label="Gender", max_length=30, required=True)
    appearance = TextInput(
        label="Appearance",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )
    image = TextInput(
        label="Profile Image (URL or emoji, optional)",
        max_length=300,
        required=False,
    )

    def __init__(self, prefill: dict = None):
        super().__init__()
        if prefill:
            self.char_name.default = prefill.get("name", "")
            self.age.default = prefill.get("age", "")
            self.gender.default = prefill.get("gender", "")
            self.appearance.default = prefill.get("appearance", "")
            self.image.default = prefill.get("image", "")

    async def on_submit(self, interaction: discord.Interaction):
        data = {
            "name": self.char_name.value.strip(),
            "age": self.age.value.strip(),
            "gender": self.gender.value.strip(),
            "appearance": self.appearance.value.strip(),
            "image": self.image.value.strip() if self.image.value else "",
        }
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        cfg = load_config(guild_id)
        bloodlines = get_available_bloodlines(guild_id, user_id)

        players = load_players(guild_id)
        existing = players.get(str(user_id), {})

        view = RegisterSelectsView(
            data,
            cfg,
            bloodlines,
            existing_player=existing,
            is_edit=bool(existing),
        )
        await interaction.response.edit_message(
            content="## Register — Step 2\nChoose your character details:",
            view=view,
        )


class RegisterSelectsView(View):
    def __init__(self, step1_data: dict, cfg: dict, bloodlines: list, existing_player: dict = None, is_edit: bool = False):
        super().__init__(timeout=300)
        self.step1_data = step1_data
        self.cfg = cfg
        self.bloodlines = bloodlines
        self.existing_player = existing_player or {}
        self.is_edit = is_edit

        # Current selections (pre-fill from existing if editing)
        self.selected_faction = self.existing_player.get("faction", cfg["factions"][0] if cfg["factions"] else "")
        self.selected_rank = self.existing_player.get("rank", cfg["ranks"][0] if cfg["ranks"] else "")
        self.selected_bloodline = self.existing_player.get("bloodline", bloodlines[0] if bloodlines else "")
        self.selected_shifter = self.existing_player.get("shifter", cfg["shifters"][0] if cfg["shifters"] else "None")

        self._build()

    def _build(self):
        self.clear_items()

        faction_select = Select(
            placeholder="Choose Faction",
            options=select_options_from_list(self.cfg.get("factions", []), self.selected_faction),
            row=0,
        )
        faction_select.callback = self._faction_cb
        self.add_item(faction_select)

        rank_select = Select(
            placeholder="Choose Rank",
            options=select_options_from_list(self.cfg.get("ranks", []), self.selected_rank),
            row=1,
        )
        rank_select.callback = self._rank_cb
        self.add_item(rank_select)

        bloodline_select = Select(
            placeholder="Choose Bloodline",
            options=select_options_from_list(self.bloodlines, self.selected_bloodline),
            row=2,
        )
        bloodline_select.callback = self._bloodline_cb
        self.add_item(bloodline_select)

        shifter_select = Select(
            placeholder="Choose Shifter",
            options=select_options_from_list(self.cfg.get("shifters", []), self.selected_shifter),
            row=3,
        )
        shifter_select.callback = self._shifter_cb
        self.add_item(shifter_select)

        confirm_btn = Button(label="Confirm", style=discord.ButtonStyle.green, row=4)
        confirm_btn.callback = self._confirm_cb
        self.add_item(confirm_btn)

    async def _faction_cb(self, interaction: discord.Interaction):
        self.selected_faction = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(view=self)

    async def _rank_cb(self, interaction: discord.Interaction):
        self.selected_rank = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(view=self)

    async def _bloodline_cb(self, interaction: discord.Interaction):
        self.selected_bloodline = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(view=self)

    async def _shifter_cb(self, interaction: discord.Interaction):
        self.selected_shifter = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(view=self)

    async def _confirm_cb(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        players = load_players(guild_id)
        cfg = load_config(guild_id)

        old_player = players.get(str(user_id), {})

        player = dict(self.step1_data)
        player["faction"] = self.selected_faction
        player["rank"] = self.selected_rank
        player["bloodline"] = self.selected_bloodline
        player["shifter"] = self.selected_shifter
        player["inventory"] = old_player.get("inventory", {})

        players[str(user_id)] = player
        save_players(guild_id, players)

        member = interaction.guild.get_member(user_id)
        if member:
            if self.is_edit and old_player:
                await remove_old_roles(member, old_player, cfg)
            await assign_roles(member, player, cfg)

        display_name = interaction.user.display_name
        profile_text = format_profile_text(player, display_name)

        view = ProfileView(user_id, guild_id)
        await interaction.response.edit_message(content=profile_text, view=view)

        # Non-ephemeral channel message
        async def delete_after(msg):
            await asyncio.sleep(30)
            try:
                await msg.delete()
            except Exception:
                pass

        try:
            ch = interaction.channel
            if ch:
                action = "updated" if self.is_edit else "registered"
                msg = await ch.send(
                    f"✅ **{display_name}** has {action} their character **{player['name']}**!"
                )
                bot.loop.create_task(delete_after(msg))
        except Exception:
            pass

        # DM
        try:
            dm = await interaction.user.create_dm()
            await dm.send(f"Here is your character profile:\n\n{profile_text}")
        except Exception:
            pass


class ProfileView(View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.guild_id = guild_id
        self._add_buttons()

    def _add_buttons(self):
        self.clear_items()
        profile_btn = Button(label="Profile", style=discord.ButtonStyle.primary, row=0)
        profile_btn.callback = self._profile_tab
        self.add_item(profile_btn)

        inv_btn = Button(label="Inventory", style=discord.ButtonStyle.secondary, row=0)
        inv_btn.callback = self._inventory_tab
        self.add_item(inv_btn)

        edit_btn = Button(label="Edit Profile", style=discord.ButtonStyle.secondary, row=0)
        edit_btn.callback = self._edit_profile
        self.add_item(edit_btn)

    async def _profile_tab(self, interaction: discord.Interaction):
        players = load_players(self.guild_id)
        player = players.get(str(self.user_id), {})
        display_name = interaction.user.display_name
        profile_text = format_profile_text(player, display_name)
        await interaction.response.edit_message(content=profile_text, view=self)

    async def _inventory_tab(self, interaction: discord.Interaction):
        players = load_players(self.guild_id)
        player = players.get(str(self.user_id), {})
        items_data = load_items(self.guild_id)
        inv_text = format_inventory_text(player, items_data)
        await interaction.response.edit_message(content=inv_text, view=self)

    async def _edit_profile(self, interaction: discord.Interaction):
        players = load_players(self.guild_id)
        player = players.get(str(self.user_id), {})
        modal = RegisterModal(prefill=player)
        # We wrap submit to go through selects flow
        modal._is_edit = True
        await interaction.response.send_modal(modal)


class UnregisteredView(View):
    def __init__(self):
        super().__init__(timeout=300)
        btn = Button(label="Register Character", style=discord.ButtonStyle.green)
        btn.callback = self._register_cb
        self.add_item(btn)

    async def _register_cb(self, interaction: discord.Interaction):
        await interaction.response.send_modal(RegisterModal())


@bot.tree.command(name="profile", description="View or create your character profile")
async def profile_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    user_id = interaction.user.id
    players = load_players(guild_id)
    player = players.get(str(user_id))
    if not player:
        await interaction.response.send_message(
            "## Character Profile\n\nYou haven't registered a character yet.",
            view=UnregisteredView(),
            ephemeral=True,
        )
    else:
        display_name = interaction.user.display_name
        profile_text = format_profile_text(player, display_name)
        await interaction.response.send_message(
            content=profile_text,
            view=ProfileView(user_id, guild_id),
            ephemeral=True,
        )


# ---------------------------------------------------------------------------
# /admin — Admin panel
# ---------------------------------------------------------------------------


def is_admin():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            return False
        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            return False
        return member.guild_permissions.administrator or member.guild_permissions.manage_guild
    return app_commands.check(predicate)


def admin_panel_text(guild_id: int) -> str:
    cfg = load_config(guild_id)
    lines = [
        "## ⚙️ Admin Panel",
        "",
        "Manage roles, factions, bloodlines, and special access.",
        "",
        f"**Factions:** {', '.join(cfg.get('factions', [])) or 'None'}",
        f"**Ranks:** {', '.join(cfg.get('ranks', [])) or 'None'}",
        f"**Shifters:** {len(cfg.get('shifters', []))} configured",
        f"**Common Bloodlines:** {', '.join(cfg.get('bloodlines_common', [])) or 'None'}",
        f"**Special Bloodlines:** {', '.join(cfg.get('bloodlines_special', [])) or 'None'}",
    ]
    return "\n".join(lines)


class AdminMainView(View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self._build()

    def _build(self):
        self.clear_items()
        buttons_row0 = [
            ("Faction Roles", self._faction_roles),
            ("Rank Roles", self._rank_roles),
            ("Shifter Roles", self._shifter_roles),
            ("Bloodline Roles", self._bloodline_roles),
        ]
        for label, cb in buttons_row0:
            btn = Button(label=label, style=discord.ButtonStyle.secondary, row=0)
            btn.callback = cb
            self.add_item(btn)

        buttons_row1 = [
            ("Manage Factions", self._manage_factions),
            ("Manage Ranks", self._manage_ranks),
            ("Manage Shifters", self._manage_shifters),
        ]
        for label, cb in buttons_row1:
            btn = Button(label=label, style=discord.ButtonStyle.secondary, row=1)
            btn.callback = cb
            self.add_item(btn)

        buttons_row2 = [
            ("Manage Bloodlines", self._manage_bloodlines),
            ("Grant Special Bloodline", self._grant_bloodline),
        ]
        for label, cb in buttons_row2:
            btn = Button(label=label, style=discord.ButtonStyle.secondary, row=2)
            btn.callback = cb
            self.add_item(btn)

        done_btn = Button(label="Done", style=discord.ButtonStyle.danger, row=3)
        done_btn.callback = self._done
        self.add_item(done_btn)

    async def _faction_roles(self, interaction: discord.Interaction):
        view = RoleMappingView(self.guild_id, "faction", parent_view=self)
        await interaction.response.edit_message(
            content=role_mapping_text(self.guild_id, "faction"),
            view=view,
        )

    async def _rank_roles(self, interaction: discord.Interaction):
        view = RoleMappingView(self.guild_id, "rank", parent_view=self)
        await interaction.response.edit_message(
            content=role_mapping_text(self.guild_id, "rank"),
            view=view,
        )

    async def _shifter_roles(self, interaction: discord.Interaction):
        view = RoleMappingView(self.guild_id, "shifter", parent_view=self)
        await interaction.response.edit_message(
            content=role_mapping_text(self.guild_id, "shifter"),
            view=view,
        )

    async def _bloodline_roles(self, interaction: discord.Interaction):
        view = RoleMappingView(self.guild_id, "bloodline", parent_view=self)
        await interaction.response.edit_message(
            content=role_mapping_text(self.guild_id, "bloodline"),
            view=view,
        )

    async def _manage_factions(self, interaction: discord.Interaction):
        view = ManageListView(self.guild_id, "factions", parent_view=self)
        await interaction.response.edit_message(
            content=manage_list_text(self.guild_id, "factions"),
            view=view,
        )

    async def _manage_ranks(self, interaction: discord.Interaction):
        view = ManageListView(self.guild_id, "ranks", parent_view=self)
        await interaction.response.edit_message(
            content=manage_list_text(self.guild_id, "ranks"),
            view=view,
        )

    async def _manage_shifters(self, interaction: discord.Interaction):
        view = ManageListView(self.guild_id, "shifters", parent_view=self)
        await interaction.response.edit_message(
            content=manage_list_text(self.guild_id, "shifters"),
            view=view,
        )

    async def _manage_bloodlines(self, interaction: discord.Interaction):
        view = ManageBloodlinesView(self.guild_id, parent_view=self)
        await interaction.response.edit_message(
            content=manage_bloodlines_text(self.guild_id),
            view=view,
        )

    async def _grant_bloodline(self, interaction: discord.Interaction):
        view = GrantBloodlineView(self.guild_id, parent_view=self)
        await interaction.response.edit_message(
            content=grant_bloodline_text(self.guild_id),
            view=view,
        )

    async def _done(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Admin panel closed.", view=None)


# --- Role mapping ---

def role_mapping_text(guild_id: int, rtype: str) -> str:
    cfg = load_config(guild_id)
    mappings = cfg["roles"].get(rtype, {})
    label_map = {
        "faction": cfg.get("factions", []),
        "rank": cfg.get("ranks", []),
        "shifter": cfg.get("shifters", []),
        "bloodline": cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", []),
    }
    items = label_map.get(rtype, [])
    lines = [f"## {rtype.title()} Roles", ""]
    for item in items:
        role_id = mappings.get(item)
        lines.append(f"**{item}** — {f'<@&{role_id}>' if role_id else '*not set*'}")
    return "\n".join(lines)


class RoleMappingView(View):
    def __init__(self, guild_id: int, rtype: str, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.rtype = rtype
        self.parent_view = parent_view
        self.selected_value = None
        self._build()

    def _get_items(self):
        cfg = load_config(self.guild_id)
        mapping = {
            "faction": cfg.get("factions", []),
            "rank": cfg.get("ranks", []),
            "shifter": cfg.get("shifters", []),
            "bloodline": cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", []),
        }
        return mapping.get(self.rtype, [])

    def _build(self):
        self.clear_items()
        items = self._get_items()
        opts = select_options_from_list(items, self.selected_value)
        value_select = Select(placeholder=f"Select {self.rtype}", options=opts, row=0)
        value_select.callback = self._value_select_cb
        self.add_item(value_select)

        role_select = discord.ui.RoleSelect(placeholder="Assign a role", row=1)
        role_select.callback = self._role_select_cb
        self.add_item(role_select)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=2)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _value_select_cb(self, interaction: discord.Interaction):
        self.selected_value = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(view=self)

    async def _role_select_cb(self, interaction: discord.Interaction):
        if not self.selected_value or self.selected_value == "__none__":
            await interaction.response.send_message("Please select a value first.", ephemeral=True)
            return
        role_id = interaction.data["values"][0]
        cfg = load_config(self.guild_id)
        cfg["roles"][self.rtype][self.selected_value] = role_id
        save_config(self.guild_id, cfg)
        self._build()
        await interaction.response.edit_message(
            content=role_mapping_text(self.guild_id, self.rtype),
            view=self,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


# --- Manage list (factions, ranks, shifters) ---

def manage_list_text(guild_id: int, key: str) -> str:
    cfg = load_config(guild_id)
    items = cfg.get(key, [])
    label = key.replace("_", " ").title()
    lines = [f"## Manage {label}", ""]
    if items:
        for i in items:
            lines.append(f"- {i}")
    else:
        lines.append("*None configured*")
    return "\n".join(lines)


class AddListItemModal(Modal):
    def __init__(self, guild_id: int, key: str, parent_view: View, title_label: str = "Add Item"):
        super().__init__(title=title_label)
        self.guild_id = guild_id
        self.key = key
        self.parent_view = parent_view
        self.item_input = TextInput(label="Name", max_length=60, required=True)
        self.add_item(self.item_input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config(self.guild_id)
        val = self.item_input.value.strip()
        if val and val not in cfg.get(self.key, []):
            cfg.setdefault(self.key, []).append(val)
            save_config(self.guild_id, cfg)
        # Rebuild parent view with updated config
        self.parent_view.cfg = cfg
        await interaction.response.edit_message(
            content=manage_list_text(self.guild_id, self.key),
            view=self.parent_view,
        )


class ManageListView(View):
    def __init__(self, guild_id: int, key: str, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.key = key
        self.parent_view = parent_view
        self.cfg = load_config(guild_id)
        self._build()

    def _build(self):
        self.clear_items()
        add_btn = Button(label="Add", style=discord.ButtonStyle.green, row=0)
        add_btn.callback = self._add
        self.add_item(add_btn)

        remove_btn = Button(label="Remove", style=discord.ButtonStyle.danger, row=0)
        remove_btn.callback = self._show_remove
        self.add_item(remove_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _add(self, interaction: discord.Interaction):
        label_map = {"factions": "Add Faction", "ranks": "Add Rank", "shifters": "Add Shifter"}
        modal = AddListItemModal(
            self.guild_id,
            self.key,
            self,
            title_label=label_map.get(self.key, "Add Item"),
        )
        await interaction.response.send_modal(modal)

    async def _show_remove(self, interaction: discord.Interaction):
        cfg = load_config(self.guild_id)
        items = cfg.get(self.key, [])
        view = RemoveListItemView(self.guild_id, self.key, items, parent_view=self)
        await interaction.response.edit_message(
            content=f"Select a **{self.key.rstrip('s')}** to remove:",
            view=view,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


class RemoveListItemView(View):
    def __init__(self, guild_id: int, key: str, items: list, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.key = key
        self.parent_view = parent_view
        opts = select_options_from_list(items)
        sel = Select(placeholder="Select to remove", options=opts, row=0)
        sel.callback = self._remove_cb
        self.add_item(sel)
        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _remove_cb(self, interaction: discord.Interaction):
        val = interaction.data["values"][0]
        if val == "__none__":
            await interaction.response.edit_message(content="Nothing to remove.", view=self.parent_view)
            return
        cfg = load_config(self.guild_id)
        lst = cfg.get(self.key, [])
        if val in lst:
            lst.remove(val)
            cfg[self.key] = lst
            save_config(self.guild_id, cfg)
        self.parent_view.cfg = cfg
        await interaction.response.edit_message(
            content=manage_list_text(self.guild_id, self.key),
            view=self.parent_view,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=manage_list_text(self.guild_id, self.key),
            view=self.parent_view,
        )


# --- Manage bloodlines ---

def manage_bloodlines_text(guild_id: int) -> str:
    cfg = load_config(guild_id)
    common = cfg.get("bloodlines_common", [])
    special = cfg.get("bloodlines_special", [])
    lines = [
        "## Manage Bloodlines",
        "",
        "**Common Bloodlines:**",
    ]
    if common:
        for b in common:
            lines.append(f"- {b}")
    else:
        lines.append("- *None*")
    lines.append("")
    lines.append("**Special Bloodlines:**")
    if special:
        for b in special:
            lines.append(f"- {b}")
    else:
        lines.append("- *None*")
    return "\n".join(lines)


class AddBloodlineModal(Modal):
    def __init__(self, guild_id: int, key: str, parent_view: View):
        label = "Add Common Bloodline" if key == "bloodlines_common" else "Add Special Bloodline"
        super().__init__(title=label)
        self.guild_id = guild_id
        self.key = key
        self.parent_view = parent_view
        self.name_input = TextInput(label="Bloodline Name", max_length=60, required=True)
        self.add_item(self.name_input)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = load_config(self.guild_id)
        val = self.name_input.value.strip()
        all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
        if val and val not in all_bl:
            cfg.setdefault(self.key, []).append(val)
            save_config(self.guild_id, cfg)
        await interaction.response.edit_message(
            content=manage_bloodlines_text(self.guild_id),
            view=self.parent_view,
        )


class ManageBloodlinesView(View):
    def __init__(self, guild_id: int, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.parent_view = parent_view
        self._build()

    def _build(self):
        self.clear_items()

        add_common_btn = Button(label="Add Common", style=discord.ButtonStyle.green, row=0)
        add_common_btn.callback = self._add_common
        self.add_item(add_common_btn)

        add_special_btn = Button(label="Add Special", style=discord.ButtonStyle.green, row=0)
        add_special_btn.callback = self._add_special
        self.add_item(add_special_btn)

        remove_btn = Button(label="Remove", style=discord.ButtonStyle.danger, row=0)
        remove_btn.callback = self._show_remove
        self.add_item(remove_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _add_common(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            AddBloodlineModal(self.guild_id, "bloodlines_common", self)
        )

    async def _add_special(self, interaction: discord.Interaction):
        await interaction.response.send_modal(
            AddBloodlineModal(self.guild_id, "bloodlines_special", self)
        )

    async def _show_remove(self, interaction: discord.Interaction):
        cfg = load_config(self.guild_id)
        all_bl = cfg.get("bloodlines_common", []) + cfg.get("bloodlines_special", [])
        view = RemoveBloodlineView(self.guild_id, all_bl, parent_view=self)
        await interaction.response.edit_message(
            content="Select a bloodline to remove:",
            view=view,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


class RemoveBloodlineView(View):
    def __init__(self, guild_id: int, bloodlines: list, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.parent_view = parent_view
        opts = select_options_from_list(bloodlines)
        sel = Select(placeholder="Select bloodline to remove", options=opts, row=0)
        sel.callback = self._remove_cb
        self.add_item(sel)
        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _remove_cb(self, interaction: discord.Interaction):
        val = interaction.data["values"][0]
        if val == "__none__":
            await interaction.response.edit_message(
                content=manage_bloodlines_text(self.guild_id),
                view=self.parent_view,
            )
            return
        cfg = load_config(self.guild_id)
        for key in ("bloodlines_common", "bloodlines_special"):
            lst = cfg.get(key, [])
            if val in lst:
                lst.remove(val)
                cfg[key] = lst
        save_config(self.guild_id, cfg)
        await interaction.response.edit_message(
            content=manage_bloodlines_text(self.guild_id),
            view=self.parent_view,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=manage_bloodlines_text(self.guild_id),
            view=self.parent_view,
        )


# --- Grant special bloodline ---

def grant_bloodline_text(guild_id: int) -> str:
    cfg = load_config(guild_id)
    special = cfg.get("bloodlines_special", [])
    access = cfg.get("special_access", {})
    lines = ["## Grant Special Bloodline Access", ""]
    if not special:
        lines.append("*No special bloodlines configured.*")
    else:
        lines.append(f"**Special Bloodlines:** {', '.join(special)}")
    lines.append("")
    if access:
        lines.append("**Current Grants:**")
        for uid, bls in access.items():
            lines.append(f"- <@{uid}>: {', '.join(bls)}")
    else:
        lines.append("*No special access granted yet.*")
    return "\n".join(lines)


class GrantBloodlineView(View):
    def __init__(self, guild_id: int, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.selected_bloodline = None
        self.selected_users: list[str] = []
        self.selected_role_id: str = None
        self._build()

    def _build(self):
        self.clear_items()
        cfg = load_config(self.guild_id)
        special = cfg.get("bloodlines_special", [])
        opts = select_options_from_list(special, self.selected_bloodline)
        bl_select = Select(placeholder="Choose special bloodline", options=opts, row=0)
        bl_select.callback = self._bl_cb
        self.add_item(bl_select)

        user_select = discord.ui.UserSelect(
            placeholder="Select users to grant",
            min_values=1,
            max_values=25,
            row=1,
        )
        user_select.callback = self._user_select_cb
        self.add_item(user_select)

        role_select = discord.ui.RoleSelect(placeholder="Grant via role", row=2)
        role_select.callback = self._role_select_cb
        self.add_item(role_select)

        grant_users_btn = Button(label="Grant to Selected Users", style=discord.ButtonStyle.green, row=3)
        grant_users_btn.callback = self._grant_users
        self.add_item(grant_users_btn)

        grant_role_btn = Button(label="Grant via Role", style=discord.ButtonStyle.green, row=3)
        grant_role_btn.callback = self._grant_role
        self.add_item(grant_role_btn)

        revoke_btn = Button(label="Revoke", style=discord.ButtonStyle.danger, row=4)
        revoke_btn.callback = self._revoke_panel
        self.add_item(revoke_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=4)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _bl_cb(self, interaction: discord.Interaction):
        self.selected_bloodline = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(view=self)

    async def _user_select_cb(self, interaction: discord.Interaction):
        self.selected_users = interaction.data["values"]
        await interaction.response.defer()

    async def _role_select_cb(self, interaction: discord.Interaction):
        self.selected_role_id = interaction.data["values"][0] if interaction.data["values"] else None
        await interaction.response.defer()

    async def _grant_users(self, interaction: discord.Interaction):
        if not self.selected_bloodline or self.selected_bloodline == "__none__":
            await interaction.response.send_message("Select a bloodline first.", ephemeral=True)
            return
        cfg = load_config(self.guild_id)
        access = cfg.setdefault("special_access", {})
        for uid in self.selected_users:
            user_access = access.setdefault(uid, [])
            if self.selected_bloodline not in user_access:
                user_access.append(self.selected_bloodline)
        save_config(self.guild_id, cfg)
        await interaction.response.edit_message(
            content=grant_bloodline_text(self.guild_id),
            view=self,
        )

    async def _grant_role(self, interaction: discord.Interaction):
        if not self.selected_bloodline or self.selected_bloodline == "__none__":
            await interaction.response.send_message("Select a bloodline first.", ephemeral=True)
            return
        if not self.selected_role_id:
            await interaction.response.send_message("Select a role first.", ephemeral=True)
            return
        guild = interaction.guild
        role = guild.get_role(int(self.selected_role_id))
        if not role:
            await interaction.response.send_message("Role not found.", ephemeral=True)
            return
        cfg = load_config(self.guild_id)
        access = cfg.setdefault("special_access", {})
        for member in role.members:
            user_access = access.setdefault(str(member.id), [])
            if self.selected_bloodline not in user_access:
                user_access.append(self.selected_bloodline)
        save_config(self.guild_id, cfg)
        await interaction.response.edit_message(
            content=grant_bloodline_text(self.guild_id),
            view=self,
        )

    async def _revoke_panel(self, interaction: discord.Interaction):
        view = RevokeBloodlineView(self.guild_id, parent_view=self)
        await interaction.response.edit_message(
            content="## Revoke Special Bloodline\nSelect users and bloodline to revoke:",
            view=view,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


class RevokeBloodlineView(View):
    def __init__(self, guild_id: int, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.selected_users: list[str] = []
        self.selected_bloodline = None
        self._build()

    def _build(self):
        self.clear_items()
        user_select = discord.ui.UserSelect(
            placeholder="Select users to revoke from",
            min_values=1,
            max_values=25,
            row=0,
        )
        user_select.callback = self._user_cb
        self.add_item(user_select)

        cfg = load_config(self.guild_id)
        special = cfg.get("bloodlines_special", [])
        opts = select_options_from_list(special, self.selected_bloodline)
        bl_select = Select(placeholder="Bloodline to revoke", options=opts, row=1)
        bl_select.callback = self._bl_cb
        self.add_item(bl_select)

        revoke_btn = Button(label="Revoke", style=discord.ButtonStyle.danger, row=2)
        revoke_btn.callback = self._do_revoke
        self.add_item(revoke_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=2)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _user_cb(self, interaction: discord.Interaction):
        self.selected_users = interaction.data["values"]
        await interaction.response.defer()

    async def _bl_cb(self, interaction: discord.Interaction):
        self.selected_bloodline = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(view=self)

    async def _do_revoke(self, interaction: discord.Interaction):
        if not self.selected_bloodline or self.selected_bloodline == "__none__":
            await interaction.response.send_message("Select a bloodline first.", ephemeral=True)
            return
        cfg = load_config(self.guild_id)
        access = cfg.setdefault("special_access", {})
        for uid in self.selected_users:
            user_access = access.get(uid, [])
            if self.selected_bloodline in user_access:
                user_access.remove(self.selected_bloodline)
                if not user_access:
                    del access[uid]
        save_config(self.guild_id, cfg)
        await interaction.response.edit_message(
            content=grant_bloodline_text(self.guild_id),
            view=self.parent_view,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=grant_bloodline_text(self.guild_id),
            view=self.parent_view,
        )


@bot.tree.command(name="admin", description="Admin panel for the AoT bot")
@is_admin()
async def admin_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    view = AdminMainView(guild_id)
    await interaction.response.send_message(
        content=admin_panel_text(guild_id),
        view=view,
        ephemeral=True,
    )


@admin_cmd.error
async def admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    await interaction.response.send_message("You need administrator permissions.", ephemeral=True)


# ---------------------------------------------------------------------------
# /item-admin — Item admin panel
# ---------------------------------------------------------------------------


def item_admin_panel_text(guild_id: int) -> str:
    items_data = load_items(guild_id)
    cats = items_data.get("categories", {})
    all_items = items_data.get("items", {})
    lines = [
        "## 🗃️ Item Admin Panel",
        "",
        f"**Categories:** {len(cats)}",
        f"**Items:** {len(all_items)}",
    ]
    return "\n".join(lines)


class ItemAdminMainView(View):
    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self._build()

    def _build(self):
        self.clear_items()
        row0 = [
            ("Categories", self._categories),
            ("Create Item", self._create_item),
            ("Edit Item", self._edit_item),
        ]
        for label, cb in row0:
            btn = Button(label=label, style=discord.ButtonStyle.secondary, row=0)
            btn.callback = cb
            self.add_item(btn)

        row1 = [
            ("Give Items", self._give_items),
            ("Remove Items", self._remove_items),
            ("View Item", self._view_item),
        ]
        for label, cb in row1:
            btn = Button(label=label, style=discord.ButtonStyle.secondary, row=1)
            btn.callback = cb
            self.add_item(btn)

        done_btn = Button(label="Done", style=discord.ButtonStyle.danger, row=2)
        done_btn.callback = self._done
        self.add_item(done_btn)

    async def _categories(self, interaction: discord.Interaction):
        view = CategoriesView(self.guild_id, parent_view=self)
        await interaction.response.edit_message(
            content=categories_text(self.guild_id),
            view=view,
        )

    async def _create_item(self, interaction: discord.Interaction):
        modal = CreateItemModal(self.guild_id, item_id=None, parent_view=self)
        await interaction.response.send_modal(modal)

    async def _edit_item(self, interaction: discord.Interaction):
        view = EditItemSelectView(self.guild_id, parent_view=self)
        await interaction.response.edit_message(
            content="Select an item to edit:",
            view=view,
        )

    async def _give_items(self, interaction: discord.Interaction):
        view = GiveRemoveItemsView(self.guild_id, mode="give", parent_view=self)
        await interaction.response.edit_message(
            content="## Give Items\nSelect item and targets:",
            view=view,
        )

    async def _remove_items(self, interaction: discord.Interaction):
        view = GiveRemoveItemsView(self.guild_id, mode="remove", parent_view=self)
        await interaction.response.edit_message(
            content="## Remove Items\nSelect item and targets:",
            view=view,
        )

    async def _view_item(self, interaction: discord.Interaction):
        view = ViewItemSelectView(self.guild_id, parent_view=self)
        await interaction.response.edit_message(
            content="Select an item to view:",
            view=view,
        )

    async def _done(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="Item admin panel closed.", view=None)


# --- Categories ---

def categories_text(guild_id: int) -> str:
    items_data = load_items(guild_id)
    cats = items_data.get("categories", {})
    cat_order = items_data.get("category_order", [])
    lines = ["## Categories", ""]
    if not cats:
        lines.append("*No categories configured.*")
    else:
        for i, cat_id in enumerate(cat_order):
            if cat_id in cats:
                cat = cats[cat_id]
                emoji = cat.get("emoji", "📦")
                name = cat.get("name", cat_id)
                lines.append(f"`{cat_id}` {emoji} **{name}** (pos {i+1})")
    return "\n".join(lines)


class AddCategoryModal(Modal, title="Add Category"):
    cat_name = TextInput(label="Category Name", max_length=60, required=True)
    cat_emoji = TextInput(label="Emoji (optional)", max_length=20, required=False)

    def __init__(self, guild_id: int, parent_view: View):
        super().__init__()
        self.guild_id = guild_id
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        name = self.cat_name.value.strip()
        emoji = self.cat_emoji.value.strip() if self.cat_emoji.value else "📦"
        cat_id = slugify(name)
        if not cat_id:
            await interaction.response.send_message("Invalid category name.", ephemeral=True)
            return
        items_data = load_items(self.guild_id)
        if cat_id not in items_data["categories"]:
            items_data["categories"][cat_id] = {"name": name, "emoji": emoji}
            items_data["category_order"].append(cat_id)
            save_items(self.guild_id, items_data)
        await interaction.response.edit_message(
            content=categories_text(self.guild_id),
            view=self.parent_view,
        )


class CategoriesView(View):
    def __init__(self, guild_id: int, parent_view: View, selected_cat: str = None):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.parent_view = parent_view
        self.selected_cat = selected_cat
        self._build()

    def _build(self):
        self.clear_items()
        items_data = load_items(self.guild_id)
        cats = items_data.get("categories", {})
        cat_order = items_data.get("category_order", [])

        if cats:
            opts = [
                discord.SelectOption(
                    label=f"{cats[c].get('emoji','📦')} {cats[c].get('name',c)}",
                    value=c,
                    default=(c == self.selected_cat),
                )
                for c in cat_order if c in cats
            ]
            if not opts:
                opts = [discord.SelectOption(label="No categories", value="__none__")]
        else:
            opts = [discord.SelectOption(label="No categories", value="__none__")]

        cat_sel = Select(placeholder="Select category", options=opts, row=0)
        cat_sel.callback = self._select_cat
        self.add_item(cat_sel)

        add_btn = Button(label="Add Category", style=discord.ButtonStyle.green, row=1)
        add_btn.callback = self._add_category
        self.add_item(add_btn)

        del_btn = Button(label="Delete Category", style=discord.ButtonStyle.danger, row=1)
        del_btn.callback = self._delete_category
        self.add_item(del_btn)

        move_up_btn = Button(label="Move Up", style=discord.ButtonStyle.secondary, row=2)
        move_up_btn.callback = self._move_up
        self.add_item(move_up_btn)

        move_down_btn = Button(label="Move Down", style=discord.ButtonStyle.secondary, row=2)
        move_down_btn.callback = self._move_down
        self.add_item(move_down_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=3)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _select_cat(self, interaction: discord.Interaction):
        val = interaction.data["values"][0]
        self.selected_cat = val if val != "__none__" else None
        self._build()
        await interaction.response.edit_message(view=self)

    async def _add_category(self, interaction: discord.Interaction):
        modal = AddCategoryModal(self.guild_id, parent_view=self)
        await interaction.response.send_modal(modal)

    async def _delete_category(self, interaction: discord.Interaction):
        if not self.selected_cat:
            await interaction.response.send_message("Select a category first.", ephemeral=True)
            return
        items_data = load_items(self.guild_id)
        cats = items_data.get("categories", {})
        cat_order = items_data.get("category_order", [])
        if self.selected_cat in cats:
            del cats[self.selected_cat]
        if self.selected_cat in cat_order:
            cat_order.remove(self.selected_cat)
        self.selected_cat = None
        save_items(self.guild_id, items_data)
        self._build()
        await interaction.response.edit_message(
            content=categories_text(self.guild_id),
            view=self,
        )

    async def _move_up(self, interaction: discord.Interaction):
        if not self.selected_cat:
            await interaction.response.send_message("Select a category first.", ephemeral=True)
            return
        items_data = load_items(self.guild_id)
        cat_order = items_data.get("category_order", [])
        if self.selected_cat in cat_order:
            idx = cat_order.index(self.selected_cat)
            if idx > 0:
                cat_order[idx], cat_order[idx - 1] = cat_order[idx - 1], cat_order[idx]
                save_items(self.guild_id, items_data)
        self._build()
        await interaction.response.edit_message(
            content=categories_text(self.guild_id),
            view=self,
        )

    async def _move_down(self, interaction: discord.Interaction):
        if not self.selected_cat:
            await interaction.response.send_message("Select a category first.", ephemeral=True)
            return
        items_data = load_items(self.guild_id)
        cat_order = items_data.get("category_order", [])
        if self.selected_cat in cat_order:
            idx = cat_order.index(self.selected_cat)
            if idx < len(cat_order) - 1:
                cat_order[idx], cat_order[idx + 1] = cat_order[idx + 1], cat_order[idx]
                save_items(self.guild_id, items_data)
        self._build()
        await interaction.response.edit_message(
            content=categories_text(self.guild_id),
            view=self,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=item_admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


# --- Create / Edit Item ---

class CreateItemModal(Modal, title="Create Item"):
    item_name = TextInput(label="Item Name", max_length=60, required=True)
    category = TextInput(label="Category Name or ID", max_length=60, required=False)
    description = TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        max_length=400,
        required=False,
    )
    emoji = TextInput(label="Emoji (optional)", max_length=20, required=False)
    image_url = TextInput(label="Image URL (optional)", max_length=400, required=False)

    def __init__(self, guild_id: int, item_id: str | None, parent_view: View, prefill: dict = None):
        super().__init__()
        self.guild_id = guild_id
        self.item_id = item_id
        self.parent_view = parent_view
        if prefill:
            self.item_name.default = prefill.get("name", "")
            self.category.default = prefill.get("category", "")
            self.description.default = prefill.get("description", "")
            self.emoji.default = prefill.get("emoji", "")
            self.image_url.default = prefill.get("image_url", "")

    async def on_submit(self, interaction: discord.Interaction):
        name = self.item_name.value.strip()
        cat_input = self.category.value.strip() if self.category.value else ""
        desc = self.description.value.strip() if self.description.value else ""
        item_emoji = self.emoji.value.strip() if self.emoji.value else "📦"
        img = self.image_url.value.strip() if self.image_url.value else ""

        items_data = load_items(self.guild_id)
        cats = items_data.get("categories", {})

        # Resolve category
        cat_id = ""
        if cat_input:
            # Try exact ID match
            if cat_input in cats:
                cat_id = cat_input
            else:
                # Try name match
                for cid, cdata in cats.items():
                    if cdata.get("name", "").lower() == cat_input.lower():
                        cat_id = cid
                        break
                if not cat_id:
                    cat_id = slugify(cat_input)

        item_id = self.item_id if self.item_id else slugify(name)
        if not item_id:
            await interaction.response.send_message("Invalid item name.", ephemeral=True)
            return

        item = {
            "name": name,
            "category": cat_id,
            "description": desc,
            "emoji": item_emoji,
            "image_url": img,
            "sell_price": items_data.get("items", {}).get(item_id, {}).get("sell_price", 0),
        }
        items_data.setdefault("items", {})[item_id] = item
        save_items(self.guild_id, items_data)

        action = "updated" if self.item_id else "created"
        text = f"✅ Item **{name}** (`{item_id}`) {action}.\n\n{item_admin_panel_text(self.guild_id)}"
        await interaction.response.edit_message(
            content=text,
            view=self.parent_view,
        )


class EditItemSelectView(View):
    def __init__(self, guild_id: int, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.parent_view = parent_view
        self._build()

    def _build(self):
        self.clear_items()
        items_data = load_items(self.guild_id)
        all_items = items_data.get("items", {})
        if all_items:
            opts = [
                discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name', iid)}",
                    value=iid,
                )
                for iid, d in list(all_items.items())[:25]
            ]
        else:
            opts = [discord.SelectOption(label="No items", value="__none__")]

        sel = Select(placeholder="Select item to edit", options=opts, row=0)
        sel.callback = self._select_cb
        self.add_item(sel)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _select_cb(self, interaction: discord.Interaction):
        item_id = interaction.data["values"][0]
        if item_id == "__none__":
            await interaction.response.send_message("No items to edit.", ephemeral=True)
            return
        items_data = load_items(self.guild_id)
        item = items_data.get("items", {}).get(item_id, {})
        prefill = {
            "name": item.get("name", ""),
            "category": item.get("category", ""),
            "description": item.get("description", ""),
            "emoji": item.get("emoji", ""),
            "image_url": item.get("image_url", ""),
        }
        modal = CreateItemModal(self.guild_id, item_id=item_id, parent_view=self.parent_view, prefill=prefill)
        modal.title = "Edit Item"
        await interaction.response.send_modal(modal)

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=item_admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


# --- View Item ---

class ViewItemSelectView(View):
    def __init__(self, guild_id: int, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.parent_view = parent_view
        self._build()

    def _build(self):
        self.clear_items()
        items_data = load_items(self.guild_id)
        all_items = items_data.get("items", {})
        if all_items:
            opts = [
                discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name', iid)}",
                    value=iid,
                )
                for iid, d in list(all_items.items())[:25]
            ]
        else:
            opts = [discord.SelectOption(label="No items", value="__none__")]

        sel = Select(placeholder="Select item to view", options=opts, row=0)
        sel.callback = self._select_cb
        self.add_item(sel)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _select_cb(self, interaction: discord.Interaction):
        item_id = interaction.data["values"][0]
        if item_id == "__none__":
            await interaction.response.send_message("No items to view.", ephemeral=True)
            return
        items_data = load_items(self.guild_id)
        item = items_data.get("items", {}).get(item_id)
        if not item:
            await interaction.response.send_message("Item not found.", ephemeral=True)
            return
        cats = items_data.get("categories", {})
        cat_id = item.get("category", "")
        cat_name = cats.get(cat_id, {}).get("name", cat_id) if cat_id else "*Uncategorized*"
        lines = [
            f"## {item.get('emoji','📦')} {item.get('name','?')}",
            f"-# `{item_id}`",
            "",
            f"**Category:** {cat_name}",
            f"**Description:** {item.get('description','*None*') or '*None*'}",
            f"**Emoji:** {item.get('emoji','📦')}",
        ]
        if item.get("image_url"):
            lines.append(f"**Image:** [View]({item['image_url']})")
        lines.append(f"**Sell Price:** {item.get('sell_price', 0)}")
        self._build()
        await interaction.response.edit_message(content="\n".join(lines), view=self)

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=item_admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


# --- Give / Remove Items ---

class SetQuantityModal(Modal, title="Set Quantity"):
    quantity = TextInput(label="Quantity", max_length=10, required=True, default="1")

    async def on_submit(self, interaction: discord.Interaction):
        # Handled by the parent view callback
        await interaction.response.defer()


class GiveRemoveItemsView(View):
    def __init__(self, guild_id: int, mode: str, parent_view: View):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.mode = mode  # "give" or "remove"
        self.parent_view = parent_view
        self.selected_item_id: str = None
        self.selected_users: list[str] = []
        self.selected_role_id: str = None
        self.quantity: int = 1
        self._build()

    def _build(self):
        self.clear_items()
        items_data = load_items(self.guild_id)
        all_items = items_data.get("items", {})

        if all_items:
            opts = [
                discord.SelectOption(
                    label=f"{d.get('emoji','📦')} {d.get('name', iid)}",
                    value=iid,
                    default=(iid == self.selected_item_id),
                )
                for iid, d in list(all_items.items())[:25]
            ]
        else:
            opts = [discord.SelectOption(label="No items", value="__none__")]

        item_sel = Select(placeholder="Select item", options=opts, row=0)
        item_sel.callback = self._item_cb
        self.add_item(item_sel)

        user_sel = discord.ui.UserSelect(
            placeholder="Select users",
            min_values=1,
            max_values=25,
            row=1,
        )
        user_sel.callback = self._user_cb
        self.add_item(user_sel)

        role_sel = discord.ui.RoleSelect(placeholder="Give/Remove via role", row=2)
        role_sel.callback = self._role_cb
        self.add_item(role_sel)

        label_a = "Give to Selected Users" if self.mode == "give" else "Remove from Selected Users"
        label_b = "Give via Role" if self.mode == "give" else "Remove via Role"

        action_users_btn = Button(label=label_a, style=discord.ButtonStyle.green, row=3)
        action_users_btn.callback = self._action_users
        self.add_item(action_users_btn)

        action_role_btn = Button(label=label_b, style=discord.ButtonStyle.green, row=3)
        action_role_btn.callback = self._action_role
        self.add_item(action_role_btn)

        set_qty_btn = Button(label=f"Set Qty (now: {self.quantity})", style=discord.ButtonStyle.secondary, row=4)
        set_qty_btn.callback = self._set_qty
        self.add_item(set_qty_btn)

        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary, row=4)
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _item_cb(self, interaction: discord.Interaction):
        val = interaction.data["values"][0]
        self.selected_item_id = val if val != "__none__" else None
        self._build()
        await interaction.response.edit_message(view=self)

    async def _user_cb(self, interaction: discord.Interaction):
        self.selected_users = interaction.data["values"]
        await interaction.response.defer()

    async def _role_cb(self, interaction: discord.Interaction):
        self.selected_role_id = interaction.data["values"][0] if interaction.data["values"] else None
        await interaction.response.defer()

    async def _set_qty(self, interaction: discord.Interaction):
        modal = SetQuantityModal()

        async def on_modal_submit(inter: discord.Interaction):
            try:
                qty = int(modal.quantity.value.strip())
                if qty < 1:
                    qty = 1
                self.quantity = qty
            except ValueError:
                pass
            self._build()
            await inter.response.edit_message(view=self)

        modal.on_submit = on_modal_submit
        await interaction.response.send_modal(modal)

    def _apply_give_remove(self, players: dict, user_id_str: str, item_id: str, qty: int):
        player = players.setdefault(user_id_str, {"inventory": {}})
        inv = player.setdefault("inventory", {})
        if self.mode == "give":
            inv[item_id] = inv.get(item_id, 0) + qty
        else:
            inv[item_id] = max(0, inv.get(item_id, 0) - qty)

    async def _action_users(self, interaction: discord.Interaction):
        if not self.selected_item_id:
            await interaction.response.send_message("Select an item first.", ephemeral=True)
            return
        if not self.selected_users:
            await interaction.response.send_message("Select at least one user.", ephemeral=True)
            return
        players = load_players(self.guild_id)
        for uid in self.selected_users:
            self._apply_give_remove(players, uid, self.selected_item_id, self.quantity)
        save_players(self.guild_id, players)
        mode_word = "given to" if self.mode == "give" else "removed from"
        cnt = len(self.selected_users)
        await interaction.response.edit_message(
            content=f"✅ Item {mode_word} {cnt} user(s).\n\n{item_admin_panel_text(self.guild_id)}",
            view=self.parent_view,
        )

    async def _action_role(self, interaction: discord.Interaction):
        if not self.selected_item_id:
            await interaction.response.send_message("Select an item first.", ephemeral=True)
            return
        if not self.selected_role_id:
            await interaction.response.send_message("Select a role first.", ephemeral=True)
            return
        guild = interaction.guild
        role = guild.get_role(int(self.selected_role_id))
        if not role:
            await interaction.response.send_message("Role not found.", ephemeral=True)
            return
        players = load_players(self.guild_id)
        cnt = 0
        for member in role.members:
            self._apply_give_remove(players, str(member.id), self.selected_item_id, self.quantity)
            cnt += 1
        save_players(self.guild_id, players)
        mode_word = "given to" if self.mode == "give" else "removed from"
        await interaction.response.edit_message(
            content=f"✅ Item {mode_word} {cnt} member(s) with role {role.name}.\n\n{item_admin_panel_text(self.guild_id)}",
            view=self.parent_view,
        )

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=item_admin_panel_text(self.guild_id),
            view=self.parent_view,
        )


@bot.tree.command(name="item-admin", description="Item admin panel for the AoT bot")
@is_admin()
async def item_admin_cmd(interaction: discord.Interaction):
    guild_id = interaction.guild_id
    view = ItemAdminMainView(guild_id)
    await interaction.response.send_message(
        content=item_admin_panel_text(guild_id),
        view=view,
        ephemeral=True,
    )


@item_admin_cmd.error
async def item_admin_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    await interaction.response.send_message("You need administrator permissions.", ephemeral=True)


# ---------------------------------------------------------------------------
# Bot events
# ---------------------------------------------------------------------------


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Online as {bot.user}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

bot.run(os.environ["DISCORD_TOKEN"])
