"""Mission & Quest system — /mission group. Embed UI, multi-channel, dropdown players."""
import time, uuid
import discord
from discord import app_commands

from aot_bot_instance import bot, GUILD2_ID, GUILD2_OBJ
from aot_shared import (
    t, load_config, save_config,
    load_players, save_players,
    load_items, save_items,
    load_missions, save_missions,
    format_full_player_info, log_event,
    cv2_dm,
)

_PER_PAGE = 5


def _is_admin_check(ix: discord.Interaction) -> bool:
    m = ix.guild.get_member(ix.user.id) if ix.guild else None
    return bool(m and (m.guild_permissions.administrator or m.guild_permissions.manage_guild))


# ── Mission group ─────────────────────────────────────────────────────────────

mission_group = app_commands.Group(
    name="mission",
    description="Mission and quest commands | คำสั่งภารกิจ",
)


@mission_group.command(name="open", description="Browse available missions | ดูภารกิจที่มีอยู่")
async def mission_open(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    view = MissionListView(ix.guild_id, ix.user.id)
    await ix.response.send_message(embed=view._embed(), view=view, ephemeral=True)


@mission_group.command(name="admin", description="[Admin] Mission management panel | จัดการภารกิจ")
async def mission_admin_cmd(ix: discord.Interaction):
    if not ix.guild or ix.guild.id != GUILD2_ID: return
    if not _is_admin_check(ix):
        await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True); return
    view = MissionAdminView(ix.guild_id, ix.guild)
    await ix.response.send_message(embed=view._embed(), view=view, ephemeral=True)


bot.tree.add_command(mission_group, guild=GUILD2_OBJ)


# ── Embed helpers ─────────────────────────────────────────────────────────────

def _mission_list_embed(gid: int, missions: list, page: int, total_pages: int) -> discord.Embed:
    embed = discord.Embed(
        title=t(gid, "mission_title"),
        color=0xe67e22,
    )
    if not missions:
        embed.description = t(gid, "no_missions")
    else:
        for mid, m in missions:
            cur_p  = len(m.get("players", {}))
            max_p  = m.get("max_players", 0)
            cap    = f"{max_p}" if max_p else "∞"
            embed.add_field(
                name=m["name"],
                value=f"{m.get('description','')[:120]}\n**Players:** {cur_p}/{cap}",
                inline=False,
            )
    embed.set_footer(text=t(gid, "page_label", page=page + 1, total=total_pages))
    return embed


def _mission_admin_embed(gid: int, sel_mid: str = None, db: dict = None) -> discord.Embed:
    if db is None:
        db = load_missions(gid)
    missions = db.get("missions", {})
    active   = {mid: m for mid, m in missions.items() if m.get("status") == "active"}
    embed    = discord.Embed(title=t(gid, "mission_admin_title"), color=0xe67e22)
    if not active:
        embed.description = t(gid, "no_missions")
    else:
        embed.description = f"**{len(active)}** active mission(s)"
    if sel_mid and sel_mid in active:
        m = active[sel_mid]
        cur_p = len(m.get("players", {}))
        max_p = m.get("max_players", 0)
        cap   = f"{max_p}" if max_p else "∞"
        post_chs = ", ".join(f"<#{c}>" for c in m.get("channels", [])) or "*none*"
        log_chs  = ", ".join(f"<#{c}>" for c in m.get("log_channels", [])) or "*none*"
        embed.add_field(name="Selected Mission", value=f"**{m['name']}** ({cur_p}/{cap})", inline=False)
        embed.add_field(name="Description", value=m.get("description", "—")[:200], inline=False)
        embed.add_field(name="Post Channels", value=post_chs, inline=True)
        embed.add_field(name="Log Channels",  value=log_chs,  inline=True)
    return embed


# ── Player: Mission List ──────────────────────────────────────────────────────

class MissionListView(discord.ui.View):
    def __init__(self, gid: int, uid: int, page: int = 0):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.page = page
        self._build()

    def _active_missions(self):
        db = load_missions(self.gid)
        return [(mid, m) for mid, m in db.get("missions", {}).items()
                if m.get("status") == "active"]

    def _embed(self) -> discord.Embed:
        active = self._active_missions()
        total_pages = max(1, (len(active) + _PER_PAGE - 1) // _PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        chunk = active[self.page * _PER_PAGE:(self.page + 1) * _PER_PAGE]
        return _mission_list_embed(self.gid, chunk, self.page, total_pages)

    def _build(self):
        self.clear_items()
        active = self._active_missions()
        total_pages = max(1, (len(active) + _PER_PAGE - 1) // _PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        chunk = active[self.page * _PER_PAGE:(self.page + 1) * _PER_PAGE]

        row = 0
        for mid, m in chunk:
            joined = str(self.uid) in m.get("players", {})
            max_p  = m.get("max_players", 0)
            full   = max_p > 0 and len(m.get("players", {})) >= max_p
            lbl    = f"✅ Joined — {m['name'][:30]}" if joined else f"Join: {m['name'][:40]}"
            jb = discord.ui.Button(
                label=lbl[:80],
                style=discord.ButtonStyle.secondary if joined else discord.ButtonStyle.success,
                disabled=(joined or full), row=row,
            )
            vb = discord.ui.Button(
                label=f"👥 {m['name'][:30]}",
                style=discord.ButtonStyle.secondary,
                row=row,
            )
            jb.callback = self._make_join(mid)
            vb.callback = self._make_view(mid)
            self.add_item(jb)
            self.add_item(vb)
            row = min(row + 1, 4)

        nav_row = min(row, 4)
        prev_btn = discord.ui.Button(
            label=t(self.gid, "prev_btn"), style=discord.ButtonStyle.secondary,
            disabled=(self.page == 0), row=nav_row,
        )
        next_btn = discord.ui.Button(
            label=t(self.gid, "next_btn"), style=discord.ButtonStyle.secondary,
            disabled=(self.page >= total_pages - 1), row=nav_row,
        )
        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, row=nav_row,
        )
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        done_btn.callback = self._done
        self.add_item(prev_btn); self.add_item(next_btn); self.add_item(done_btn)

    def _make_join(self, mid):
        async def _join(ix: discord.Interaction):
            players = load_players(self.gid)
            player  = players.get(str(self.uid), {})
            if not player:
                await ix.response.send_message(t(self.gid, "not_registered_join"), ephemeral=True); return
            db = load_missions(self.gid)
            m  = db["missions"].get(mid)
            if not m:
                await ix.response.send_message("Mission not found.", ephemeral=True); return
            if str(self.uid) in m.get("players", {}):
                await ix.response.send_message(t(self.gid, "already_joined_mission"), ephemeral=True); return
            max_p = m.get("max_players", 0)
            if max_p > 0 and len(m.get("players", {})) >= max_p:
                await ix.response.send_message(t(self.gid, "mission_full", max=max_p), ephemeral=True); return
            display = ix.user.display_name
            m.setdefault("players", {})[str(self.uid)] = {
                "joined_at":    time.time(),
                "display_name": display,
                "character":    dict(player),
            }
            save_missions(self.gid, db)
            await log_event(bot, self.gid, "mission", f"{display} joined mission '{m['name']}'")
            for g in bot.guilds:
                if g.id == self.gid:
                    for member in g.members:
                        if member.guild_permissions.administrator:
                            try:
                                await cv2_dm(member, t(self.gid, "mission_notify_admin",
                                                       user=display, mission=m["name"]))
                            except Exception:
                                pass
                    break
            self._build()
            await ix.response.edit_message(embed=self._embed(), view=self)
        return _join

    def _make_view(self, mid):
        async def _view(ix):
            view = MissionPlayersView(self.gid, mid, self)
            await ix.response.edit_message(embed=view._embed(), view=view)
        return _view

    async def _prev(self, ix):
        self.page -= 1; self._build()
        await ix.response.edit_message(embed=self._embed(), view=self)

    async def _next(self, ix):
        self.page += 1; self._build()
        await ix.response.edit_message(embed=self._embed(), view=self)

    async def _done(self, ix):
        embed = discord.Embed(description=f"*{t(self.gid, 'panel_closed')}*", color=0x2f3136)
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)


# ── Mission Players (dropdown select) ────────────────────────────────────────

class MissionPlayersView(discord.ui.View):
    def __init__(self, gid: int, mid: str, parent, sel_uid: str = None):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent; self.sel_uid = sel_uid
        self._build()

    def _embed(self) -> discord.Embed:
        db = load_missions(self.gid)
        m  = db.get("missions", {}).get(self.mid, {})
        players = m.get("players", {})
        embed = discord.Embed(
            title=f"{t(self.gid, 'mission_players_title')} — {m.get('name', '')}",
            description=f"**{len(players)}** player(s) joined",
            color=0x3498db,
        )
        if self.sel_uid and self.sel_uid in players:
            pdata = players[self.sel_uid]
            char  = pdata.get("character", {})
            name  = pdata.get("display_name", self.sel_uid)
            embed.add_field(
                name=f"📋 {name}",
                value=format_full_player_info(char, name, self.gid)[:1024],
                inline=False,
            )
        return embed

    def _build(self):
        self.clear_items()
        db = load_missions(self.gid)
        m  = db.get("missions", {}).get(self.mid, {})
        players = m.get("players", {})

        if players:
            opts = [
                discord.SelectOption(
                    label=pdata.get("display_name", uid)[:100],
                    value=uid,
                    default=(uid == self.sel_uid),
                )
                for uid, pdata in list(players.items())[:25]
            ]
            sel = discord.ui.Select(placeholder="View player info…", options=opts, row=0)
            sel.callback = self._on_select
            self.add_item(sel)

        back_btn = discord.ui.Button(
            label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=1,
        )
        back_btn.callback = self._back
        self.add_item(back_btn)

    async def _on_select(self, ix: discord.Interaction):
        self.sel_uid = ix.data["values"][0]; self._build()
        await ix.response.edit_message(embed=self._embed(), view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)


# ── Admin: Mission Admin View ─────────────────────────────────────────────────

class MissionAdminView(discord.ui.View):
    def __init__(self, gid: int, guild, sel_mid: str = None):
        super().__init__(timeout=300)
        self.gid = gid; self.guild = guild; self.sel_mid = sel_mid
        self._build()

    def _embed(self) -> discord.Embed:
        return _mission_admin_embed(self.gid, self.sel_mid)

    def _build(self):
        self.clear_items()
        db      = load_missions(self.gid)
        active  = {mid: m for mid, m in db.get("missions", {}).items()
                   if m.get("status") == "active"}

        if active:
            opts = [
                discord.SelectOption(label=m["name"][:100], value=mid,
                                     default=(mid == self.sel_mid))
                for mid, m in list(active.items())[:25]
            ]
            sel = discord.ui.Select(placeholder="Select mission…", options=opts, row=0)
            sel.callback = self._sel
            self.add_item(sel)

        create_btn = discord.ui.Button(
            label=t(self.gid, "create_mission_btn"), style=discord.ButtonStyle.success, row=1,
        )
        done_btn = discord.ui.Button(
            label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, row=1,
        )
        create_btn.callback = self._create
        done_btn.callback   = self._done
        self.add_item(create_btn); self.add_item(done_btn)

        if self.sel_mid and self.sel_mid in active:
            drops_btn  = discord.ui.Button(label=t(self.gid, "configure_drops_btn"),  style=discord.ButtonStyle.secondary, row=2)
            view_p_btn = discord.ui.Button(label=t(self.gid, "view_players_btn"),     style=discord.ButtonStyle.secondary, row=2)
            finish_btn = discord.ui.Button(label=t(self.gid, "finish_mission_btn"),   style=discord.ButtonStyle.success,   row=2)
            ch_btn     = discord.ui.Button(label=t(self.gid, "mission_channels_btn"), style=discord.ButtonStyle.secondary, row=3)
            del_btn    = discord.ui.Button(label=t(self.gid, "delete_mission_btn"),   style=discord.ButtonStyle.danger,    row=3)

            drops_btn.callback  = self._drops
            view_p_btn.callback = self._view_players
            finish_btn.callback = self._finish
            ch_btn.callback     = self._channels
            del_btn.callback    = self._delete

            self.add_item(drops_btn); self.add_item(view_p_btn); self.add_item(finish_btn)
            self.add_item(ch_btn); self.add_item(del_btn)

    async def _sel(self, ix):
        v = ix.data["values"][0]
        self.sel_mid = v if v != "__none__" else None
        self._build()
        await ix.response.edit_message(embed=self._embed(), view=self)

    async def _create(self, ix):
        await ix.response.send_modal(CreateMissionModal(self.gid, self))

    async def _drops(self, ix):
        view = MissionDropsView(self.gid, self.sel_mid, self)
        await ix.response.edit_message(embed=view._embed(), view=view)

    async def _view_players(self, ix):
        view = MissionPlayersView(self.gid, self.sel_mid, self)
        await ix.response.edit_message(embed=view._embed(), view=view)

    async def _finish(self, ix):
        await ix.response.send_modal(MissionLogModal(self.gid, self.sel_mid, self))

    async def _channels(self, ix):
        view = MissionChannelsView(self.gid, self.sel_mid, self, self.guild)
        await ix.response.edit_message(embed=view._embed(), view=view)

    async def _delete(self, ix):
        db = load_missions(self.gid)
        db["missions"].pop(self.sel_mid, None)
        save_missions(self.gid, db)
        self.sel_mid = None
        self._build()
        await ix.response.edit_message(embed=self._embed(), view=self)

    async def _done(self, ix):
        embed = discord.Embed(description=f"*{t(self.gid, 'panel_closed')}*", color=0x2f3136)
        self.clear_items()
        await ix.response.edit_message(embed=embed, view=None)


# ── Create Mission Modal ──────────────────────────────────────────────────────

class CreateMissionModal(discord.ui.Modal, title="Create Mission"):
    f_name = discord.ui.TextInput(label="Mission Name", max_length=60)
    f_desc = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph,
                                  max_length=500, required=False)
    f_max  = discord.ui.TextInput(label="Max Players (0 = unlimited)", max_length=5, default="0")

    def __init__(self, gid: int, parent):
        super().__init__()
        self.gid = gid; self.parent = parent
        self.f_name.label = t(gid, "mission_name_field")
        self.f_desc.label = t(gid, "mission_desc_field")
        self.f_max.label  = t(gid, "mission_max_field")

    async def on_submit(self, ix: discord.Interaction):
        try: max_p = max(0, int(self.f_max.value.strip() or "0"))
        except: max_p = 0
        mid = str(uuid.uuid4())[:8]
        db  = load_missions(self.gid)
        db["missions"][mid] = {
            "id":           mid,
            "name":         self.f_name.value.strip(),
            "description":  (self.f_desc.value or "").strip(),
            "max_players":  max_p,
            "status":       "active",
            "channels":     [],
            "log_channels": [],
            "created_by":   str(ix.user.id),
            "created_at":   time.time(),
            "players":      {},
            "item_drops":   {"all": [], "targeted": {}},
            "coin_rewards":  {},
            "log_text":     "",
        }
        save_missions(self.gid, db)
        await log_event(bot, self.gid, "mission",
                        f"{ix.user.display_name} created mission '{self.f_name.value.strip()}'")
        self.parent.sel_mid = mid
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)
        # Post to board channels
        await _post_to_board_channels(self.gid, db["missions"][mid], ix.guild)


# ── Mission Channels Config ───────────────────────────────────────────────────

class MissionChannelsView(discord.ui.View):
    def __init__(self, gid: int, mid: str, parent, guild):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent; self.guild = guild
        self._build()

    def _embed(self) -> discord.Embed:
        db = load_missions(self.gid)
        m  = db.get("missions", {}).get(self.mid, {})
        post_names = ", ".join(f"<#{c}>" for c in m.get("channels", [])) or "*none*"
        log_names  = ", ".join(f"<#{c}>" for c in m.get("log_channels", [])) or "*none*"
        embed = discord.Embed(title="Mission Channel Configuration", color=0x3498db)
        embed.add_field(name="Post Channels", value=post_names, inline=False)
        embed.add_field(name="Log Channels",  value=log_names,  inline=False)
        return embed

    def _build(self):
        self.clear_items()
        post_sel = discord.ui.ChannelSelect(
            placeholder="Add post channel",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=0,
        )
        log_sel = discord.ui.ChannelSelect(
            placeholder="Add log channel",
            channel_types=[discord.ChannelType.text, discord.ChannelType.news],
            row=1,
        )
        post_sel.callback = self._add_post
        log_sel.callback  = self._add_log
        self.add_item(post_sel); self.add_item(log_sel)

        clear_post = discord.ui.Button(label="Clear post channels", style=discord.ButtonStyle.danger,    row=2)
        clear_log  = discord.ui.Button(label="Clear log channels",  style=discord.ButtonStyle.danger,    row=2)
        bk_btn     = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=2)
        clear_post.callback = self._clear_post
        clear_log.callback  = self._clear_log
        bk_btn.callback     = self._back
        self.add_item(clear_post); self.add_item(clear_log); self.add_item(bk_btn)

    async def _add_post(self, ix):
        db = load_missions(self.gid)
        cid = str(ix.data["values"][0])
        m   = db["missions"].get(self.mid)
        if m and cid not in m.get("channels", []):
            m.setdefault("channels", []).append(cid)
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(embed=self._embed(), view=self)

    async def _add_log(self, ix):
        db = load_missions(self.gid)
        cid = str(ix.data["values"][0])
        m   = db["missions"].get(self.mid)
        if m and cid not in m.get("log_channels", []):
            m.setdefault("log_channels", []).append(cid)
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(embed=self._embed(), view=self)

    async def _clear_post(self, ix):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["channels"] = []
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(embed=self._embed(), view=self)

    async def _clear_log(self, ix):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["log_channels"] = []
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(embed=self._embed(), view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)


# ── Mission Drops Config ──────────────────────────────────────────────────────

class MissionDropsView(discord.ui.View):
    def __init__(self, gid: int, mid: str, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent
        self._build()

    def _embed(self) -> discord.Embed:
        db    = load_missions(self.gid)
        drops = db.get("missions", {}).get(self.mid, {}).get("item_drops", {"all": [], "targeted": {}})
        coins = db.get("missions", {}).get(self.mid, {}).get("coin_rewards", {})
        embed = discord.Embed(title="🎁 Configure Rewards", color=0xf1c40f)
        all_lines = [f"• {d.get('item_name','?')} ×{d.get('qty',1)}" for d in drops.get("all", [])]
        embed.add_field(name="Items (all players)", value="\n".join(all_lines) or "—", inline=False)
        if drops.get("targeted"):
            t_lines = []
            for uid, udrops in list(drops["targeted"].items())[:10]:
                for d in udrops[:3]:
                    t_lines.append(f"<@{uid}>: {d.get('item_name','?')} ×{d.get('qty',1)}")
            embed.add_field(name="Items (targeted)", value="\n".join(t_lines) or "—", inline=False)
        if coins:
            coin_lines = [f"<@{uid}>: {amt}" for uid, amt in list(coins.items())[:10]]
            embed.add_field(name="Coin Rewards", value="\n".join(coin_lines) or "—", inline=False)
        return embed

    def _build(self):
        self.clear_items()
        bk_btn     = discord.ui.Button(label=t(self.gid, "back_btn"),         style=discord.ButtonStyle.secondary, row=0)
        all_btn    = discord.ui.Button(label=t(self.gid, "drop_for_all_btn"), style=discord.ButtonStyle.primary,   row=0)
        target_btn = discord.ui.Button(label=t(self.gid, "drop_for_player_btn"), style=discord.ButtonStyle.secondary, row=0)
        coin_btn   = discord.ui.Button(label="Coin Reward (player)",          style=discord.ButtonStyle.secondary, row=1)
        clear_btn  = discord.ui.Button(label="Clear All",                     style=discord.ButtonStyle.danger,    row=1)
        bk_btn.callback     = self._back
        all_btn.callback    = self._add_for_all
        target_btn.callback = self._add_for_target
        coin_btn.callback   = self._add_coin
        clear_btn.callback  = self._clear
        self.add_item(bk_btn); self.add_item(all_btn); self.add_item(target_btn)
        self.add_item(coin_btn); self.add_item(clear_btn)

    async def _add_for_all(self, ix):
        await ix.response.send_modal(_DropModal(self.gid, self.mid, None, self))

    async def _add_for_target(self, ix):
        view = _DropTargetSelectView(self.gid, self.mid, self)
        await ix.response.edit_message(embed=view._embed(), view=view)

    async def _add_coin(self, ix):
        view = _CoinTargetSelectView(self.gid, self.mid, self)
        await ix.response.edit_message(embed=view._embed(), view=view)

    async def _clear(self, ix):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["item_drops"]  = {"all": [], "targeted": {}}
            db["missions"][self.mid]["coin_rewards"] = {}
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(embed=self._embed(), view=self)

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)


class _DropTargetSelectView(discord.ui.View):
    def __init__(self, gid: int, mid: str, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent
        self._build()

    def _embed(self) -> discord.Embed:
        return discord.Embed(title="Select player for targeted drop", color=0xe67e22)

    def _build(self):
        self.clear_items()
        db = load_missions(self.gid)
        players = db.get("missions", {}).get(self.mid, {}).get("players", {})
        opts = ([discord.SelectOption(label=pdata.get("display_name", uid)[:100], value=uid)
                 for uid, pdata in list(players.items())[:25]]
                or [discord.SelectOption(label="No players", value="__none__")])
        sel = discord.ui.Select(placeholder="Select player…", options=opts, row=0)
        sel.callback = self._sel
        self.add_item(sel)
        bk = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=1)
        bk.callback = self._back
        self.add_item(bk)

    async def _sel(self, ix):
        uid = ix.data["values"][0]
        if uid == "__none__": await ix.response.defer(); return
        await ix.response.send_modal(_DropModal(self.gid, self.mid, uid, self.parent))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)


class _CoinTargetSelectView(discord.ui.View):
    def __init__(self, gid: int, mid: str, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent
        self._build()

    def _embed(self) -> discord.Embed:
        return discord.Embed(title="Select player for coin reward", color=0xf1c40f)

    def _build(self):
        self.clear_items()
        db = load_missions(self.gid)
        players = db.get("missions", {}).get(self.mid, {}).get("players", {})
        opts = ([discord.SelectOption(label=pdata.get("display_name", uid)[:100], value=uid)
                 for uid, pdata in list(players.items())[:25]]
                or [discord.SelectOption(label="No players", value="__none__")])
        sel = discord.ui.Select(placeholder="Select player…", options=opts, row=0)
        sel.callback = self._sel
        self.add_item(sel)
        bk = discord.ui.Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, row=1)
        bk.callback = self._back
        self.add_item(bk)

    async def _sel(self, ix):
        uid = ix.data["values"][0]
        if uid == "__none__": await ix.response.defer(); return
        await ix.response.send_modal(_CoinRewardModal(self.gid, self.mid, uid, self.parent))

    async def _back(self, ix):
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)


class _DropModal(discord.ui.Modal, title="Add Item Drop"):
    f_item = discord.ui.TextInput(label="Item Name", max_length=60)
    f_qty  = discord.ui.TextInput(label="Quantity",  max_length=5, default="1")

    def __init__(self, gid: int, mid: str, target_uid, parent):
        super().__init__()
        self.gid = gid; self.mid = mid; self.target_uid = target_uid; self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        try: qty = max(1, int(self.f_qty.value.strip() or "1"))
        except: qty = 1
        item_name = self.f_item.value.strip()
        db = load_missions(self.gid)
        m  = db["missions"].get(self.mid)
        if m:
            drop_data = {"item_name": item_name, "qty": qty}
            if self.target_uid:
                m["item_drops"].setdefault("targeted", {}).setdefault(self.target_uid, []).append(drop_data)
            else:
                m["item_drops"].setdefault("all", []).append(drop_data)
        save_missions(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)
        await ix.followup.send(t(self.gid, "mission_drop_added"), ephemeral=True)


class _CoinRewardModal(discord.ui.Modal, title="Coin Reward"):
    f_amount = discord.ui.TextInput(label="Coin Amount", max_length=10)

    def __init__(self, gid: int, mid: str, target_uid: str, parent):
        super().__init__()
        self.gid = gid; self.mid = mid; self.target_uid = target_uid; self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        try: amount = max(0, int(self.f_amount.value.strip()))
        except: amount = 0
        if amount <= 0:
            await ix.response.send_message("Amount must be positive.", ephemeral=True); return
        db = load_missions(self.gid)
        m  = db["missions"].get(self.mid)
        if m:
            m.setdefault("coin_rewards", {})[self.target_uid] = amount
        save_missions(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)
        await ix.followup.send(f"Coin reward set: {amount} for <@{self.target_uid}>", ephemeral=True)


# ── Finish Mission Modal ──────────────────────────────────────────────────────

class MissionLogModal(discord.ui.Modal, title="Mission Log"):
    f_log = discord.ui.TextInput(label="Mission Log", style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, gid: int, mid: str, parent):
        super().__init__()
        self.gid = gid; self.mid = mid; self.parent = parent
        self.f_log.label = t(gid, "mission_log_field")

    async def on_submit(self, ix: discord.Interaction):
        db = load_missions(self.gid)
        m  = db["missions"].get(self.mid)
        if not m:
            await ix.response.send_message("Mission not found.", ephemeral=True); return

        m["status"]       = "completed"
        m["completed_at"] = time.time()
        m["log_text"]     = self.f_log.value.strip()
        save_missions(self.gid, db)

        await _distribute_drops(self.gid, m, ix.guild)
        await _post_mission_log(self.gid, m, ix.guild)
        await log_event(bot, self.gid, "mission",
                        f"{ix.user.display_name} completed mission '{m['name']}'")

        self.parent.sel_mid = None
        self.parent._build()
        await ix.response.edit_message(embed=self.parent._embed(), view=self.parent)
        await ix.followup.send(t(self.gid, "mission_completed", name=m["name"]), ephemeral=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _post_to_board_channels(gid: int, mission: dict, guild):
    """Post mission announcement to all board channels."""
    if not guild: return
    cfg = load_config(gid)
    board_chs = cfg.get("mission_channels", []) or mission.get("channels", [])
    embed = discord.Embed(
        title=f"📋 New Mission: {mission['name']}",
        description=mission.get("description", ""),
        color=0xe67e22,
    )
    max_p = mission.get("max_players", 0)
    embed.add_field(name="Max Players", value=f"{max_p}" if max_p else "Unlimited", inline=True)
    for cid in board_chs:
        ch = guild.get_channel(int(cid))
        if ch:
            try: await ch.send(embed=embed)
            except Exception: pass


async def _distribute_drops(gid: int, mission: dict, guild):
    players_db = load_players(gid)
    items_db   = load_items(gid)
    all_items  = items_db.get("items", {})
    drops      = mission.get("item_drops", {})
    coins      = mission.get("coin_rewards", {})

    def _find_item_id(name: str):
        for iid, item in all_items.items():
            if item.get("name", "").lower() == name.lower():
                return iid
        return None

    for uid in mission.get("players", {}):
        player = players_db.get(uid, {})
        if not player: continue

        all_drops = drops.get("all", []) + drops.get("targeted", {}).get(uid, [])
        changed = False
        for drop in all_drops:
            iid = _find_item_id(drop.get("item_name", ""))
            if not iid: continue
            qty = drop.get("qty", 1)
            player.setdefault("inventory", {})[iid] = (
                player["inventory"].get(iid, 0) + qty
            )
            changed = True
            if guild:
                member = guild.get_member(int(uid))
                if member:
                    await cv2_dm(member, t(gid, "mission_drop_given",
                                           item=drop["item_name"], qty=qty))

        if uid in coins:
            coin_amt = coins[uid]
            player["balance"] = player.get("balance", 0) + coin_amt
            changed = True
            if guild:
                member = guild.get_member(int(uid))
                if member:
                    await cv2_dm(member, f"You received **{coin_amt}** coins from mission **{mission['name']}**!")

        if changed:
            players_db[uid] = player

    save_players(gid, players_db)


async def _post_mission_log(gid: int, mission: dict, guild):
    if not guild: return
    player_list = [f"• {pdata.get('display_name', uid)}"
                   for uid, pdata in mission.get("players", {}).items()]
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(mission.get("completed_at", time.time())))

    embed = discord.Embed(
        title=f"📋 Mission Log — {mission['name']}",
        description=f"*Completed: {ts}*",
        color=0x2ecc71,
    )
    embed.add_field(name="Description", value=mission.get("description", "—")[:400], inline=False)
    embed.add_field(
        name=f"Participants ({len(player_list)})",
        value="\n".join(player_list[:20]) or "—",
        inline=False,
    )
    embed.add_field(name="Log", value=mission.get("log_text", "—")[:1024], inline=False)

    for ch_id in mission.get("log_channels", []):
        ch = guild.get_channel(int(ch_id))
        if ch:
            try: await ch.send(embed=embed)
            except Exception: pass
