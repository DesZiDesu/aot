"""Mission & Quest system — /mission group (Embed + discord.ui.View only)."""
import time
import uuid

import discord
from discord import app_commands
from discord.ui import Modal, TextInput

from core.instance import bot
from core.shared import (
    EMBED_COLOR,
    format_full_player_info,
    load_items,
    load_missions,
    load_players,
    log_event,
    save_missions,
    save_players,
    t,
)

_PER_PAGE = 5


# ── Permission helper ─────────────────────────────────────────────────────────

def _member_is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


# ── Slash command group ───────────────────────────────────────────────────────

mission_group = app_commands.Group(
    name="mission",
    description="Mission and quest commands",
    description_localizations={"th": "คำสั่งภารกิจ"},
)


@mission_group.command(
    name="open",
    description="Browse available missions",
    description_localizations={"th": "ดูภารกิจที่เปิดรับ"},
)
async def mission_open(ix: discord.Interaction):
    embed, view = _build_mission_list(ix.guild_id, ix.user.id, page=0)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


@mission_group.command(
    name="admin",
    description="Admin mission management panel",
    description_localizations={"th": "แผงจัดการภารกิจสำหรับแอดมิน"},
)
async def mission_admin_cmd(ix: discord.Interaction):
    if not ix.guild:
        return
    m = ix.guild.get_member(ix.user.id)
    if not m or not _member_is_admin(m):
        embed = discord.Embed(description=t(ix.guild_id, "admin_only"), color=EMBED_COLOR)
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    embed, view = _build_mission_admin(ix.guild_id, ix.guild, sel_mid=None)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


bot.tree.add_command(mission_group)


# ── Mission List helpers ──────────────────────────────────────────────────────

def _build_mission_list(gid: int, uid: int, page: int = 0):
    """Return (embed, MissionListView)."""
    db = load_missions(gid)
    active = [(mid, m) for mid, m in db.get("missions", {}).items()
              if m.get("status") == "active"]
    total_pages = max(1, (len(active) + _PER_PAGE - 1) // _PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = active[page * _PER_PAGE:(page + 1) * _PER_PAGE]

    embed = discord.Embed(
        title=t(gid, "mission_title"),
        color=EMBED_COLOR,
    )
    embed.set_footer(text=t(gid, "page_label", page=page + 1, total=total_pages))

    if not chunk:
        embed.description = t(gid, "no_missions")
    else:
        for mid, m in chunk:
            max_p = m.get("max_players", 0)
            cur_p = len(m.get("players", {}))
            joined = str(uid) in m.get("players", {})
            full = max_p > 0 and cur_p >= max_p
            status = "✅ Joined" if joined else ("🔒 Full" if full else "⚔️ Open")
            embed.add_field(
                name=f"{m['name']}  [{status}]",
                value=(
                    f"*{m.get('description', '')[:120]}*\n"
                    f"Players: **{cur_p}/{max_p if max_p else '∞'}**"
                ),
                inline=False,
            )

    view = MissionListView(gid=gid, uid=uid, page=page,
                           chunk=chunk, total_pages=total_pages)
    return embed, view


class MissionListView(discord.ui.View):
    """Player mission browse view — select to join or view players."""

    def __init__(self, gid: int, uid: int, page: int,
                 chunk: list, total_pages: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.page = page
        self.total_pages = total_pages

        # ── Row 0: Back / Done button ──────────────────────────────────────
        done_btn = discord.ui.Button(
            label=t(gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="ml_done",
            row=0,
        )
        done_btn.callback = self._done
        self.add_item(done_btn)

        # ── Row 1: Mission select (join) ───────────────────────────────────
        if chunk:
            join_opts = []
            for mid, m in chunk:
                max_p = m.get("max_players", 0)
                cur_p = len(m.get("players", {}))
                joined = str(uid) in m.get("players", {})
                full = max_p > 0 and cur_p >= max_p
                desc = "Joined" if joined else ("Full" if full else f"{cur_p}/{max_p if max_p else '∞'}")
                join_opts.append(discord.SelectOption(
                    label=m["name"][:100],
                    value=mid,
                    description=desc[:100],
                ))

            join_sel = discord.ui.Select(
                placeholder=t(gid, "join_mission_btn"),
                options=join_opts,
                custom_id="ml_join_sel",
                row=1,
            )
            join_sel.callback = self._join_selected
            self.add_item(join_sel)

            # Row 2: View Players select
            view_opts = [
                discord.SelectOption(label=m["name"][:100], value=mid)
                for mid, m in chunk
            ]
            view_sel = discord.ui.Select(
                placeholder=t(gid, "view_players_btn"),
                options=view_opts,
                custom_id="ml_view_sel",
                row=2,
            )
            view_sel.callback = self._view_selected
            self.add_item(view_sel)

        # ── Row 3: Pagination ──────────────────────────────────────────────
        prev_btn = discord.ui.Button(
            label=t(gid, "prev_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="ml_prev",
            disabled=(page == 0),
            row=3,
        )
        next_btn = discord.ui.Button(
            label=t(gid, "next_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="ml_next",
            disabled=(page >= total_pages - 1),
            row=3,
        )
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        self.add_item(prev_btn)
        self.add_item(next_btn)

    # ── Callbacks ─────────────────────────────────────────────────────────

    async def _join_selected(self, ix: discord.Interaction):
        mid = ix.data["values"][0]
        players = load_players(self.gid)
        player = players.get(str(self.uid), {})
        if not player:
            await ix.response.send_message(
                t(self.gid, "not_registered_join"), ephemeral=True)
            return
        db = load_missions(self.gid)
        m = db["missions"].get(mid)
        if not m:
            await ix.response.send_message("Mission not found.", ephemeral=True)
            return
        if str(self.uid) in m.get("players", {}):
            await ix.response.send_message(
                t(self.gid, "already_joined_mission"), ephemeral=True)
            return
        max_p = m.get("max_players", 0)
        if max_p > 0 and len(m.get("players", {})) >= max_p:
            await ix.response.send_message(
                t(self.gid, "mission_full", max=max_p), ephemeral=True)
            return
        display = ix.user.display_name
        m.setdefault("players", {})[str(self.uid)] = {
            "joined_at": time.time(),
            "display_name": display,
            "character": dict(player),
        }
        save_missions(self.gid, db)

        # notify log channels
        await log_event(bot, self.gid, "mission",
                        f"{display} joined mission '{m['name']}'")
        for ch_id in m.get("log_channels", []):
            guild_obj = ix.guild
            if guild_obj:
                ch = guild_obj.get_channel(int(ch_id))
                if ch:
                    notify_embed = discord.Embed(
                        description=t(self.gid, "mission_notify_admin",
                                      user=display, mission=m["name"]),
                        color=EMBED_COLOR,
                    )
                    try:
                        await ch.send(embed=notify_embed)
                    except Exception:
                        pass

        embed, view = _build_mission_list(self.gid, self.uid, self.page)
        await ix.response.edit_message(embed=embed, view=view)
        await ix.followup.send(
            t(self.gid, "mission_joined", name=m["name"]), ephemeral=True)

    async def _view_selected(self, ix: discord.Interaction):
        mid = ix.data["values"][0]
        embed, view = _build_mission_players(self.gid, mid, page=0,
                                              back_page=self.page, back_uid=self.uid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _prev(self, ix: discord.Interaction):
        embed, view = _build_mission_list(self.gid, self.uid, self.page - 1)
        await ix.response.edit_message(embed=embed, view=view)

    async def _next(self, ix: discord.Interaction):
        embed, view = _build_mission_list(self.gid, self.uid, self.page + 1)
        await ix.response.edit_message(embed=embed, view=view)

    async def _done(self, ix: discord.Interaction):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=None)


# ── Mission Players helpers ───────────────────────────────────────────────────

def _build_mission_players(gid: int, mid: str, page: int = 0,
                            back_page: int = 0, back_uid: int = 0):
    """Return (embed, MissionPlayersView)."""
    db = load_missions(gid)
    m = db.get("missions", {}).get(mid, {})
    players = m.get("players", {})
    items = list(players.items())
    total_pages = max(1, (len(items) + _PER_PAGE - 1) // _PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = items[page * _PER_PAGE:(page + 1) * _PER_PAGE]

    embed = discord.Embed(
        title=f"{t(gid, 'mission_players_title')} — {m.get('name', '')}",
        color=EMBED_COLOR,
    )
    embed.set_footer(text=t(gid, "page_label", page=page + 1, total=total_pages))

    if not chunk:
        embed.description = t(gid, "no_missions")
    else:
        for uid, pdata in chunk:
            char = pdata.get("character", {})
            name = pdata.get("display_name", uid)
            embed.add_field(
                name=f"━ {name}",
                value=format_full_player_info(char, name, gid)[:1024],
                inline=False,
            )

    view = MissionPlayersView(gid=gid, mid=mid, page=page,
                               total_pages=total_pages,
                               back_page=back_page, back_uid=back_uid)
    return embed, view


class MissionPlayersView(discord.ui.View):
    def __init__(self, gid: int, mid: str, page: int, total_pages: int,
                 back_page: int, back_uid: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.mid = mid
        self.page = page
        self.total_pages = total_pages
        self.back_page = back_page
        self.back_uid = back_uid

        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="mpv_bk",
            row=0,
        )
        bk.callback = self._back
        self.add_item(bk)

        prev_btn = discord.ui.Button(
            label=t(gid, "prev_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="mpv_prev",
            disabled=(page == 0),
            row=1,
        )
        next_btn = discord.ui.Button(
            label=t(gid, "next_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="mpv_next",
            disabled=(page >= total_pages - 1),
            row=1,
        )
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        self.add_item(prev_btn)
        self.add_item(next_btn)

    async def _back(self, ix: discord.Interaction):
        embed, view = _build_mission_list(self.gid, self.back_uid, self.back_page)
        await ix.response.edit_message(embed=embed, view=view)

    async def _prev(self, ix: discord.Interaction):
        embed, view = _build_mission_players(
            self.gid, self.mid, self.page - 1,
            back_page=self.back_page, back_uid=self.back_uid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _next(self, ix: discord.Interaction):
        embed, view = _build_mission_players(
            self.gid, self.mid, self.page + 1,
            back_page=self.back_page, back_uid=self.back_uid)
        await ix.response.edit_message(embed=embed, view=view)


# ── Mission Admin helpers ─────────────────────────────────────────────────────

def _build_mission_admin(gid: int, guild, sel_mid: str = None):
    """Return (embed, MissionAdminView)."""
    db = load_missions(gid)
    missions = db.get("missions", {})
    active = {mid: m for mid, m in missions.items() if m.get("status") == "active"}

    embed = discord.Embed(title=t(gid, "mission_admin_title"), color=EMBED_COLOR)
    if not active:
        embed.description = t(gid, "no_missions")
    else:
        for mid, m in list(active.items())[:10]:
            cur = len(m.get("players", {}))
            max_p = m.get("max_players", 0)
            embed.add_field(
                name=m["name"],
                value=(
                    f"Players: {cur}/{max_p if max_p else '∞'}\n"
                    f"*{m.get('description', '')[:80]}*"
                ),
                inline=True,
            )

    if sel_mid and sel_mid in active:
        m = active[sel_mid]
        cur = len(m.get("players", {}))
        max_p = m.get("max_players", 0)
        embed.add_field(
            name=f"— Selected: {m['name']} —",
            value=(
                f"Players: {cur}/{max_p if max_p else '∞'}\n"
                f"Post channels: {len(m.get('channels', []))}\n"
                f"Log channels: {len(m.get('log_channels', []))}"
            ),
            inline=False,
        )

    view = MissionAdminView(gid=gid, guild=guild, active=active, sel_mid=sel_mid)
    return embed, view


class MissionAdminView(discord.ui.View):
    def __init__(self, gid: int, guild, active: dict, sel_mid: str = None):
        super().__init__(timeout=300)
        self.gid = gid
        self.guild = guild
        self.sel_mid = sel_mid

        # Row 0: select mission
        opts = (
            [discord.SelectOption(label=m["name"][:100], value=mid,
                                  default=(mid == sel_mid))
             for mid, m in list(active.items())[:25]]
            or [discord.SelectOption(label="No active missions", value="__none__")]
        )
        sel = discord.ui.Select(
            placeholder="Select mission",
            options=opts,
            custom_id="ma_sel",
            row=0,
        )
        sel.callback = self._sel
        self.add_item(sel)

        # Row 1: create / done
        create_btn = discord.ui.Button(
            label=t(gid, "create_mission_btn"),
            style=discord.ButtonStyle.green,
            custom_id="ma_create",
            row=1,
        )
        done_btn = discord.ui.Button(
            label=t(gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="ma_done",
            row=1,
        )
        create_btn.callback = self._create
        done_btn.callback = self._done
        self.add_item(create_btn)
        self.add_item(done_btn)

        if sel_mid and sel_mid in active:
            # Row 2: drops / view players
            drops_btn = discord.ui.Button(
                label=t(gid, "configure_drops_btn"),
                style=discord.ButtonStyle.secondary,
                custom_id="ma_drops",
                row=2,
            )
            view_p_btn = discord.ui.Button(
                label=t(gid, "view_players_btn"),
                style=discord.ButtonStyle.secondary,
                custom_id="ma_viewp",
                row=2,
            )
            drops_btn.callback = self._drops
            view_p_btn.callback = self._view_players
            self.add_item(drops_btn)
            self.add_item(view_p_btn)

            # Row 3: finish / channels / edit
            finish_btn = discord.ui.Button(
                label=t(gid, "finish_mission_btn"),
                style=discord.ButtonStyle.green,
                custom_id="ma_finish",
                row=3,
            )
            ch_btn = discord.ui.Button(
                label=t(gid, "mission_channels_btn"),
                style=discord.ButtonStyle.secondary,
                custom_id="ma_ch",
                row=3,
            )
            edit_btn = discord.ui.Button(
                label=t(gid, "edit_mission_btn"),
                style=discord.ButtonStyle.primary,
                custom_id="ma_edit",
                row=3,
            )
            finish_btn.callback = self._finish
            ch_btn.callback = self._channels
            edit_btn.callback = self._edit
            self.add_item(finish_btn)
            self.add_item(ch_btn)
            self.add_item(edit_btn)

            # Row 4: delete
            del_btn = discord.ui.Button(
                label=t(gid, "delete_mission_btn"),
                style=discord.ButtonStyle.danger,
                custom_id="ma_del",
                row=4,
            )
            del_btn.callback = self._delete
            self.add_item(del_btn)

    async def _sel(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        sel_mid = v if v != "__none__" else None
        embed, view = _build_mission_admin(self.gid, self.guild, sel_mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _create(self, ix: discord.Interaction):
        await ix.response.send_modal(CreateMissionModal(self.gid, self.guild))

    async def _drops(self, ix: discord.Interaction):
        embed, view = _build_drops_view(self.gid, self.sel_mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _view_players(self, ix: discord.Interaction):
        embed, view = _build_mission_players(
            self.gid, self.sel_mid, page=0, back_page=0, back_uid=0)
        # Override the back action to return to admin panel
        view._admin_back = True
        view._gid = self.gid
        view._guild = self.guild
        view._sel_mid = self.sel_mid

        async def _back_to_admin(ixx: discord.Interaction):
            emb, vw = _build_mission_admin(self.gid, self.guild, self.sel_mid)
            await ixx.response.edit_message(embed=emb, view=vw)

        # Patch the back button callback
        for item in view.children:
            if hasattr(item, "custom_id") and item.custom_id == "mpv_bk":
                item.callback = _back_to_admin
        await ix.response.edit_message(embed=embed, view=view)

    async def _finish(self, ix: discord.Interaction):
        await ix.response.send_modal(
            MissionLogModal(self.gid, self.sel_mid, self.guild))

    async def _channels(self, ix: discord.Interaction):
        embed, view = _build_channels_view(self.gid, self.sel_mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _edit(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        m = db.get("missions", {}).get(self.sel_mid, {})
        await ix.response.send_modal(
            EditMissionModal(self.gid, self.sel_mid, m, self.guild))

    async def _delete(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        db["missions"].pop(self.sel_mid, None)
        save_missions(self.gid, db)
        embed, view = _build_mission_admin(self.gid, self.guild, sel_mid=None)
        await ix.response.edit_message(embed=embed, view=view)

    async def _done(self, ix: discord.Interaction):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=None)


# ── Create Mission Modal ──────────────────────────────────────────────────────

class CreateMissionModal(Modal, title="Create Mission"):
    f_name = TextInput(label="Mission Name", max_length=60)
    f_desc = TextInput(label="Description", style=discord.TextStyle.paragraph,
                       max_length=500, required=False)
    f_max = TextInput(label="Max Players (0 = unlimited)", max_length=5, default="0")

    def __init__(self, gid: int, guild):
        super().__init__()
        self.gid = gid
        self.guild = guild
        self.f_name.label = t(gid, "mission_name_field")
        self.f_desc.label = t(gid, "mission_desc_field")
        self.f_max.label = t(gid, "mission_max_field")

    async def on_submit(self, ix: discord.Interaction):
        try:
            max_p = max(0, int(self.f_max.value.strip() or "0"))
        except Exception:
            max_p = 0
        mid = str(uuid.uuid4())[:8]
        db = load_missions(self.gid)
        db["missions"][mid] = {
            "id": mid,
            "name": self.f_name.value.strip(),
            "description": (self.f_desc.value or "").strip(),
            "max_players": max_p,
            "status": "active",
            "channels": [],
            "log_channels": [],
            "created_by": str(ix.user.id),
            "created_at": time.time(),
            "players": {},
            "item_drops": {"all": [], "targeted": {}},
            "log_text": "",
        }
        save_missions(self.gid, db)
        await log_event(bot, self.gid, "mission",
                        f"{ix.user.display_name} created mission '{self.f_name.value.strip()}'")
        embed, view = _build_mission_admin(self.gid, self.guild, sel_mid=mid)
        await ix.response.edit_message(embed=embed, view=view)


# ── Edit Mission Modal ────────────────────────────────────────────────────────

class EditMissionModal(Modal, title="Edit Mission"):
    f_name = TextInput(label="Mission Name", max_length=60)
    f_desc = TextInput(label="Description", style=discord.TextStyle.paragraph,
                       max_length=500, required=False)
    f_max = TextInput(label="Max Players (0 = unlimited)", max_length=5)

    def __init__(self, gid: int, mid: str, mission: dict, guild):
        super().__init__()
        self.gid = gid
        self.mid = mid
        self.guild = guild
        self.f_name.label = t(gid, "mission_name_field")
        self.f_desc.label = t(gid, "mission_desc_field")
        self.f_max.label = t(gid, "mission_max_field")
        self.f_name.default = mission.get("name", "")
        self.f_desc.default = mission.get("description", "")
        self.f_max.default = str(mission.get("max_players", 0))

    async def on_submit(self, ix: discord.Interaction):
        try:
            max_p = max(0, int(self.f_max.value.strip() or "0"))
        except Exception:
            max_p = 0
        db = load_missions(self.gid)
        m = db["missions"].get(self.mid)
        if m:
            m["name"] = self.f_name.value.strip()
            m["description"] = (self.f_desc.value or "").strip()
            m["max_players"] = max_p
            save_missions(self.gid, db)
        embed, view = _build_mission_admin(self.gid, self.guild, sel_mid=self.mid)
        await ix.response.edit_message(embed=embed, view=view)


# ── Channel Config ────────────────────────────────────────────────────────────

def _build_channels_view(gid: int, mid: str):
    db = load_missions(gid)
    m = db.get("missions", {}).get(mid, {})
    post_names = [f"<#{c}>" for c in m.get("channels", [])]
    log_names = [f"<#{c}>" for c in m.get("log_channels", [])]

    embed = discord.Embed(
        title="Mission Channel Configuration",
        color=EMBED_COLOR,
    )
    embed.add_field(
        name="Post Channels",
        value=", ".join(post_names) or "*none*",
        inline=False,
    )
    embed.add_field(
        name="Log Channels",
        value=", ".join(log_names) or "*none*",
        inline=False,
    )
    view = MissionChannelsView(gid=gid, mid=mid)
    return embed, view


class MissionChannelsView(discord.ui.View):
    def __init__(self, gid: int, mid: str):
        super().__init__(timeout=300)
        self.gid = gid
        self.mid = mid

        # Row 0: Back
        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="mch_bk",
            row=0,
        )
        bk.callback = self._back
        self.add_item(bk)

        # Row 1: post channel select
        post_sel = discord.ui.ChannelSelect(
            placeholder="Add post channel",
            channel_types=[discord.ChannelType.text],
            custom_id="mch_post",
            row=1,
        )
        post_sel.callback = self._add_post
        self.add_item(post_sel)

        # Row 2: log channel select
        log_sel = discord.ui.ChannelSelect(
            placeholder="Add log channel",
            channel_types=[discord.ChannelType.text],
            custom_id="mch_log",
            row=2,
        )
        log_sel.callback = self._add_log
        self.add_item(log_sel)

        # Row 3: clear buttons
        clear_post = discord.ui.Button(
            label="Clear post channels",
            style=discord.ButtonStyle.danger,
            custom_id="mch_clrp",
            row=3,
        )
        clear_log = discord.ui.Button(
            label="Clear log channels",
            style=discord.ButtonStyle.danger,
            custom_id="mch_clrl",
            row=3,
        )
        clear_post.callback = self._clear_post
        clear_log.callback = self._clear_log
        self.add_item(clear_post)
        self.add_item(clear_log)

    async def _add_post(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        cid = str(ix.data["values"][0])
        m = db["missions"].get(self.mid)
        if m and cid not in m.get("channels", []):
            m.setdefault("channels", []).append(cid)
        save_missions(self.gid, db)
        embed, view = _build_channels_view(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _add_log(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        cid = str(ix.data["values"][0])
        m = db["missions"].get(self.mid)
        if m and cid not in m.get("log_channels", []):
            m.setdefault("log_channels", []).append(cid)
        save_missions(self.gid, db)
        embed, view = _build_channels_view(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _clear_post(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["channels"] = []
        save_missions(self.gid, db)
        embed, view = _build_channels_view(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _clear_log(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["log_channels"] = []
        save_missions(self.gid, db)
        embed, view = _build_channels_view(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _back(self, ix: discord.Interaction):
        # We need the guild — retrieve from interaction
        db = load_missions(self.gid)
        active = {mid: m for mid, m in db.get("missions", {}).items()
                  if m.get("status") == "active"}
        embed, view = _build_mission_admin(self.gid, ix.guild, sel_mid=self.mid)
        await ix.response.edit_message(embed=embed, view=view)


# ── Drops Config ──────────────────────────────────────────────────────────────

def _build_drops_view(gid: int, mid: str):
    db = load_missions(gid)
    m = db.get("missions", {}).get(mid, {})
    drops = m.get("item_drops", {"all": [], "targeted": {}})

    embed = discord.Embed(title="Configure Item Drops", color=EMBED_COLOR)
    all_lines = [
        f"{d.get('item_name', '?')} × {d.get('qty', 1)}"
        for d in drops.get("all", [])
    ]
    embed.add_field(
        name="All Players",
        value="\n".join(all_lines[:15]) or "*none*",
        inline=False,
    )
    tgt_lines = []
    for uid, udrops in list(drops.get("targeted", {}).items())[:5]:
        for d in udrops[:3]:
            tgt_lines.append(f"<@{uid}>: {d.get('item_name', '?')} × {d.get('qty', 1)}")
    embed.add_field(
        name="Targeted",
        value="\n".join(tgt_lines) or "*none*",
        inline=False,
    )
    view = MissionDropsView(gid=gid, mid=mid)
    return embed, view


class MissionDropsView(discord.ui.View):
    def __init__(self, gid: int, mid: str):
        super().__init__(timeout=300)
        self.gid = gid
        self.mid = mid

        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="md_bk",
            row=0,
        )
        bk.callback = self._back
        self.add_item(bk)

        all_btn = discord.ui.Button(
            label=t(gid, "drop_for_all_btn"),
            style=discord.ButtonStyle.primary,
            custom_id="md_all",
            row=1,
        )
        target_btn = discord.ui.Button(
            label=t(gid, "drop_for_player_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="md_tgt",
            row=1,
        )
        clear_btn = discord.ui.Button(
            label="Clear All Drops",
            style=discord.ButtonStyle.danger,
            custom_id="md_clear",
            row=2,
        )
        all_btn.callback = self._add_for_all
        target_btn.callback = self._add_for_target
        clear_btn.callback = self._clear
        self.add_item(all_btn)
        self.add_item(target_btn)
        self.add_item(clear_btn)

    async def _add_for_all(self, ix: discord.Interaction):
        await ix.response.send_modal(_DropModal(self.gid, self.mid, None))

    async def _add_for_target(self, ix: discord.Interaction):
        embed, view = _build_drop_target_select(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _clear(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["item_drops"] = {"all": [], "targeted": {}}
        save_missions(self.gid, db)
        embed, view = _build_drops_view(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _back(self, ix: discord.Interaction):
        embed, view = _build_mission_admin(self.gid, ix.guild, sel_mid=self.mid)
        await ix.response.edit_message(embed=embed, view=view)


def _build_drop_target_select(gid: int, mid: str):
    db = load_missions(gid)
    mission = db.get("missions", {}).get(mid, {})
    players = mission.get("players", {})
    embed = discord.Embed(
        title="Select player for targeted drop", color=EMBED_COLOR)
    view = DropTargetSelectView(gid=gid, mid=mid, players=players)
    return embed, view


class DropTargetSelectView(discord.ui.View):
    def __init__(self, gid: int, mid: str, players: dict):
        super().__init__(timeout=300)
        self.gid = gid
        self.mid = mid

        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="dts_bk",
            row=0,
        )
        bk.callback = self._back
        self.add_item(bk)

        opts = (
            [discord.SelectOption(
                label=pdata.get("display_name", uid)[:100], value=uid)
             for uid, pdata in list(players.items())[:25]]
            or [discord.SelectOption(label="No players", value="__none__")]
        )
        sel = discord.ui.Select(
            placeholder="Select player",
            options=opts,
            custom_id="dts_sel",
            row=1,
        )
        sel.callback = self._sel
        self.add_item(sel)

    async def _sel(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        if uid == "__none__":
            await ix.response.defer()
            return
        await ix.response.send_modal(_DropModal(self.gid, self.mid, uid))

    async def _back(self, ix: discord.Interaction):
        embed, view = _build_drops_view(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)


class _DropModal(Modal, title="Add Item Drop"):
    f_item = TextInput(label="Item Name", max_length=60)
    f_qty = TextInput(label="Quantity", max_length=5, default="1")

    def __init__(self, gid: int, mid: str, target_uid):
        super().__init__()
        self.gid = gid
        self.mid = mid
        self.target_uid = target_uid

    async def on_submit(self, ix: discord.Interaction):
        try:
            qty = max(1, int(self.f_qty.value.strip() or "1"))
        except Exception:
            qty = 1
        item_name = self.f_item.value.strip()
        db = load_missions(self.gid)
        m = db["missions"].get(self.mid)
        if m:
            drop_data = {"item_name": item_name, "qty": qty}
            if self.target_uid:
                m["item_drops"].setdefault("targeted", {}).setdefault(
                    self.target_uid, []).append(drop_data)
            else:
                m["item_drops"].setdefault("all", []).append(drop_data)
        save_missions(self.gid, db)
        embed, view = _build_drops_view(self.gid, self.mid)
        await ix.response.edit_message(embed=embed, view=view)
        await ix.followup.send(t(self.gid, "mission_drop_added"), ephemeral=True)


# ── Finish Mission Modal ──────────────────────────────────────────────────────

class MissionLogModal(Modal, title="Mission Log"):
    f_log = TextInput(label="Mission Log", style=discord.TextStyle.paragraph,
                      max_length=2000)

    def __init__(self, gid: int, mid: str, guild):
        super().__init__()
        self.gid = gid
        self.mid = mid
        self.guild = guild
        self.f_log.label = t(gid, "mission_log_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        m = db["missions"].get(self.mid)
        if not m:
            await ix.response.send_message("Mission not found.", ephemeral=True)
            return

        m["status"] = "completed"
        m["completed_at"] = time.time()
        m["log_text"] = self.f_log.value.strip()
        save_missions(self.gid, db)

        await _distribute_drops(self.gid, m, self.guild)
        await _post_mission_log(self.gid, m, self.guild)
        await log_event(bot, self.gid, "mission",
                        f"{ix.user.display_name} completed mission '{m['name']}'")

        embed, view = _build_mission_admin(self.gid, self.guild, sel_mid=None)
        await ix.response.edit_message(embed=embed, view=view)
        await ix.followup.send(
            t(self.gid, "mission_completed", name=m["name"]), ephemeral=True)


# ── Drop distribution ─────────────────────────────────────────────────────────

async def _distribute_drops(gid: int, mission: dict, guild):
    players_db = load_players(gid)
    items_db = load_items(gid)
    all_items = items_db.get("items", {})
    drops = mission.get("item_drops", {})

    def _find_item_id(name: str):
        for iid, item in all_items.items():
            if item.get("name", "").lower() == name.lower():
                return iid
        return None

    for uid in mission.get("players", {}):
        player = players_db.get(uid, {})
        if not player:
            continue
        all_drops = drops.get("all", []) + drops.get("targeted", {}).get(uid, [])
        changed = False
        for drop in all_drops:
            iid = _find_item_id(drop.get("item_name", ""))
            if not iid:
                continue
            qty = drop.get("qty", 1)
            player.setdefault("inventory", {})[iid] = (
                player["inventory"].get(iid, 0) + qty
            )
            changed = True
            if guild:
                member = guild.get_member(int(uid))
                if member:
                    try:
                        dm = await member.create_dm()
                        drop_embed = discord.Embed(
                            description=t(gid, "mission_drop_given",
                                          item=drop["item_name"], qty=qty),
                            color=EMBED_COLOR,
                        )
                        await dm.send(embed=drop_embed)
                    except Exception:
                        pass
        if changed:
            players_db[uid] = player
    save_players(gid, players_db)


async def _post_mission_log(gid: int, mission: dict, guild):
    if not guild:
        return
    player_list = [
        f"• {pdata.get('display_name', uid)}"
        for uid, pdata in mission.get("players", {}).items()
    ]
    ts = time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(mission.get("completed_at", time.time())))

    embed = discord.Embed(
        title=f"Mission Log — {mission['name']}",
        color=EMBED_COLOR,
    )
    embed.add_field(name="Completed", value=ts, inline=True)
    embed.add_field(name="Participants",
                    value=str(len(player_list)), inline=True)
    embed.add_field(
        name="Description",
        value=mission.get("description", "*none*")[:1024],
        inline=False,
    )
    if player_list:
        embed.add_field(
            name="Participants",
            value="\n".join(player_list[:20]),
            inline=False,
        )
    embed.add_field(
        name="Log",
        value=mission.get("log_text", "")[:1024] or "*empty*",
        inline=False,
    )

    for ch_id in mission.get("log_channels", []):
        ch = guild.get_channel(int(ch_id))
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass
