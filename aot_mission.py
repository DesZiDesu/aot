"""Mission & Quest system — /mission group."""
import time, uuid
import discord
from discord import app_commands
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Select, Modal, TextInput)

from aot_bot_instance import bot
from aot_shared import (
    t, load_config, save_config,
    load_players, save_players,
    load_items, save_items,
    load_missions, save_missions,
    format_full_player_info, log_event,
    cv2_dm,
)

_PER_PAGE = 5


def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


# ── Mission group ─────────────────────────────────────────────────────────────

mission_group = app_commands.Group(
    name="mission",
    description="Mission and quest commands",
    description_localizations={"th": "คำสั่งภารกิจ"},
)


@mission_group.command(name="open",
                       description="Browse available missions",
                       description_localizations={"th": "ดูภารกิจที่เปิดรับ"})
async def mission_open(ix: discord.Interaction):
    await ix.response.send_message(view=MissionListView(ix.guild_id, ix.user.id), ephemeral=True)


@mission_group.command(name="admin",
                       description="Admin mission management panel",
                       description_localizations={"th": "แผงจัดการภารกิจสำหรับแอดมิน"})
async def mission_admin_cmd(ix: discord.Interaction):
    if not ix.guild:
        return
    m = ix.guild.get_member(ix.user.id)
    if not m or not (m.guild_permissions.administrator or m.guild_permissions.manage_guild):
        v = LayoutView(timeout=60)
        v.add_item(Container(TextDisplay(t(ix.guild_id, "admin_only"))))
        await ix.response.send_message(view=v, ephemeral=True)
        return
    await ix.response.send_message(view=MissionAdminView(ix.guild_id, ix.guild), ephemeral=True)


bot.tree.add_command(mission_group)


# ── Player: Mission List ──────────────────────────────────────────────────────

class MissionListView(LayoutView):
    def __init__(self, gid: int, uid: int, page: int = 0):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        db = load_missions(self.gid)
        active = [(mid, m) for mid, m in db.get("missions", {}).items()
                  if m.get("status") == "active"]
        total_pages = max(1, (len(active) + _PER_PAGE - 1) // _PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        chunk = active[self.page * _PER_PAGE:(self.page + 1) * _PER_PAGE]

        lines = [f"**{t(self.gid,'mission_title')}**", ""]
        if not chunk:
            lines.append(t(self.gid, "no_missions"))

        children = []
        mission_buttons = []

        for mid, m in chunk:
            joined   = str(self.uid) in m.get("players", {})
            max_p    = m.get("max_players", 0)
            cur_p    = len(m.get("players", {}))
            full     = (max_p > 0 and cur_p >= max_p)
            lines.append(f"**{m['name']}**")
            lines.append(f"*{m.get('description','')[:100]}*")
            lines.append(f"Players: {cur_p}/{max_p if max_p else '∞'}")
            lines.append("")

            join_lbl = "✅ Joined" if joined else t(self.gid, "join_mission_btn")
            jb = Button(label=join_lbl[:80],
                        style=discord.ButtonStyle.green if not joined else discord.ButtonStyle.secondary,
                        custom_id=f"ml_join_{mid}", disabled=(joined or full))
            vb = Button(label=t(self.gid, "view_players_btn"),
                        style=discord.ButtonStyle.secondary,
                        custom_id=f"ml_view_{mid}")
            jb.callback = self._make_join(mid)
            vb.callback = self._make_view(mid)
            mission_buttons.append(ActionRow(jb, vb))

        prev_btn = Button(label=t(self.gid, "prev_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="ml_prev", disabled=(self.page == 0))
        next_btn = Button(label=t(self.gid, "next_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="ml_next", disabled=(self.page >= total_pages - 1))
        done_btn = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger,
                          custom_id="ml_done")
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        done_btn.callback = self._done

        page_label = t(self.gid, "page_label", page=self.page + 1, total=total_pages)
        children = [
            TextDisplay("\n".join(lines)),
            Separator(),
            *mission_buttons,
            Separator(),
            ActionRow(prev_btn, next_btn),
            ActionRow(done_btn),
        ]
        self.add_item(Container(*children))

    def _make_join(self, mid):
        async def _join(ix: discord.Interaction):
            players = load_players(self.gid)
            player  = players.get(str(self.uid), {})
            if not player:
                await ix.response.send_message(t(self.gid, "not_registered_join"), ephemeral=True)
                return
            db = load_missions(self.gid)
            m  = db["missions"].get(mid)
            if not m:
                await ix.response.send_message("Mission not found.", ephemeral=True); return
            if str(self.uid) in m.get("players", {}):
                await ix.response.send_message(t(self.gid, "already_joined_mission"), ephemeral=True)
                return
            max_p = m.get("max_players", 0)
            if max_p > 0 and len(m.get("players", {})) >= max_p:
                await ix.response.send_message(t(self.gid, "mission_full", max=max_p), ephemeral=True)
                return
            display = ix.user.display_name
            m.setdefault("players", {})[str(self.uid)] = {
                "joined_at": time.time(),
                "display_name": display,
                "character": dict(player),
            }
            save_missions(self.gid, db)
            await log_event(bot, self.gid, "mission",
                            f"{display} joined mission '{m['name']}'")
            for g in bot.guilds:
                if g.id == self.gid:
                    for member in g.members:
                        if member.guild_permissions.administrator:
                            await cv2_dm(member,
                                t(self.gid, "mission_notify_admin",
                                  user=display, mission=m["name"]))
                    break
            await ix.response.send_message(
                t(self.gid, "mission_joined", name=m["name"]), ephemeral=True)
            self._build()
            await ix.edit_original_response(view=self)
        return _join

    def _make_view(self, mid):
        async def _view(ix):
            await ix.response.edit_message(
                view=MissionPlayersView(self.gid, mid, self))
        return _view

    async def _prev(self, ix):
        self.page -= 1; self._build(); await ix.response.edit_message(view=self)

    async def _next(self, ix):
        self.page += 1; self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


# ── Mission Players (paginated) ───────────────────────────────────────────────

class MissionPlayersView(LayoutView):
    def __init__(self, gid: int, mid: str, parent, page: int = 0):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent; self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        db = load_missions(self.gid)
        m  = db.get("missions", {}).get(self.mid, {})
        players = m.get("players", {})
        items   = list(players.items())

        total_pages = max(1, (len(items) + _PER_PAGE - 1) // _PER_PAGE)
        self.page = max(0, min(self.page, total_pages - 1))
        chunk = items[self.page * _PER_PAGE:(self.page + 1) * _PER_PAGE]

        lines = [f"**{t(self.gid,'mission_players_title')} — {m.get('name','')}**",
                 t(self.gid, "page_label", page=self.page + 1, total=total_pages), ""]
        for uid, pdata in chunk:
            char = pdata.get("character", {})
            name = pdata.get("display_name", uid)
            lines.append(f"━━━━━━━━━━")
            lines.append(format_full_player_info(char, name, self.gid))
            lines.append("")

        bk_btn   = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="mpv_bk")
        prev_btn = Button(label=t(self.gid, "prev_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="mpv_prev", disabled=(self.page == 0))
        next_btn = Button(label=t(self.gid, "next_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="mpv_next", disabled=(self.page >= total_pages - 1))
        bk_btn.callback   = self._back
        prev_btn.callback = self._prev
        next_btn.callback = self._next

        self.add_item(Container(
            ActionRow(bk_btn),
            Separator(),
            TextDisplay("\n".join(lines)),
            Separator(),
            ActionRow(prev_btn, next_btn),
        ))

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _prev(self, ix):
        self.page -= 1; self._build(); await ix.response.edit_message(view=self)

    async def _next(self, ix):
        self.page += 1; self._build(); await ix.response.edit_message(view=self)


# ── Admin: Mission Admin View ─────────────────────────────────────────────────

class MissionAdminView(LayoutView):
    def __init__(self, gid: int, guild, sel_mid: str = None):
        super().__init__(timeout=300)
        self.gid = gid; self.guild = guild; self.sel_mid = sel_mid
        self._build()

    def _build(self):
        self.clear_items()
        db      = load_missions(self.gid)
        missions = db.get("missions", {})
        active   = {mid: m for mid, m in missions.items() if m.get("status") == "active"}

        lines = [f"**{t(self.gid,'mission_admin_title')}**", ""]
        if not active:
            lines.append(t(self.gid, "no_missions"))

        opts = ([discord.SelectOption(label=m["name"][:100], value=mid,
                                      default=(mid == self.sel_mid))
                 for mid, m in list(active.items())[:25]]
                or [discord.SelectOption(label="No active missions", value="__none__")])
        sel = Select(placeholder="Select mission", options=opts)
        sel.callback = self._sel

        create_btn = Button(label=t(self.gid, "create_mission_btn"),
                            style=discord.ButtonStyle.green, custom_id="ma_create")
        done_btn   = Button(label=t(self.gid, "done_btn"),
                            style=discord.ButtonStyle.danger, custom_id="ma_done")
        create_btn.callback = self._create
        done_btn.callback   = self._done

        children = [TextDisplay("\n".join(lines)), Separator(), ActionRow(sel)]

        if self.sel_mid and self.sel_mid in active:
            m   = active[self.sel_mid]
            cur = len(m.get("players", {}))
            max_p = m.get("max_players", 0)
            lines2 = [
                f"**{m['name']}** ({cur}/{max_p if max_p else '∞'} players)",
                f"*{m.get('description','')[:120]}*",
                f"Channels: {len(m.get('channels',[]))} | Log channels: {len(m.get('log_channels',[]))}",
            ]
            children.append(Separator())
            children.append(TextDisplay("\n".join(lines2)))

            drops_btn  = Button(label=t(self.gid, "configure_drops_btn"),
                                style=discord.ButtonStyle.secondary, custom_id="ma_drops")
            view_p_btn = Button(label=t(self.gid, "view_players_btn"),
                                style=discord.ButtonStyle.secondary, custom_id="ma_viewp")
            finish_btn = Button(label=t(self.gid, "finish_mission_btn"),
                                style=discord.ButtonStyle.green, custom_id="ma_finish")
            ch_btn     = Button(label=t(self.gid, "mission_channels_btn"),
                                style=discord.ButtonStyle.secondary, custom_id="ma_ch")
            del_btn    = Button(label=t(self.gid, "delete_mission_btn"),
                                style=discord.ButtonStyle.danger, custom_id="ma_del")

            drops_btn.callback  = self._drops
            view_p_btn.callback = self._view_players
            finish_btn.callback = self._finish
            ch_btn.callback     = self._channels
            del_btn.callback    = self._delete

            children.append(ActionRow(drops_btn, view_p_btn))
            children.append(ActionRow(finish_btn, ch_btn))
            children.append(ActionRow(del_btn))

        children.append(ActionRow(create_btn, done_btn))
        self.add_item(Container(*children))

    async def _sel(self, ix):
        v = ix.data["values"][0]
        self.sel_mid = v if v != "__none__" else None
        self._build(); await ix.response.edit_message(view=self)

    async def _create(self, ix):
        await ix.response.send_modal(CreateMissionModal(self.gid, self))

    async def _drops(self, ix):
        await ix.response.edit_message(
            view=MissionDropsView(self.gid, self.sel_mid, self))

    async def _view_players(self, ix):
        await ix.response.edit_message(
            view=MissionPlayersView(self.gid, self.sel_mid, self))

    async def _finish(self, ix):
        await ix.response.send_modal(MissionLogModal(self.gid, self.sel_mid, self))

    async def _channels(self, ix):
        await ix.response.edit_message(
            view=MissionChannelsView(self.gid, self.sel_mid, self, self.guild))

    async def _delete(self, ix):
        db = load_missions(self.gid)
        db["missions"].pop(self.sel_mid, None)
        save_missions(self.gid, db)
        self.sel_mid = None
        self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


# ── Create Mission Modal ──────────────────────────────────────────────────────

class CreateMissionModal(Modal, title="Create Mission"):
    f_name = TextInput(label="Mission Name",        max_length=60)
    f_desc = TextInput(label="Description",         style=discord.TextStyle.paragraph,
                       max_length=500, required=False)
    f_max  = TextInput(label="Max Players (0 = unlimited)", max_length=5, default="0")

    def __init__(self, gid, parent):
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
            "id": mid,
            "name":        self.f_name.value.strip(),
            "description": (self.f_desc.value or "").strip(),
            "max_players": max_p,
            "status":      "active",
            "channels":    [],
            "log_channels": [],
            "created_by":  str(ix.user.id),
            "created_at":  time.time(),
            "players":     {},
            "item_drops":  {"all": [], "targeted": {}},
            "log_text":    "",
        }
        save_missions(self.gid, db)
        await log_event(bot, self.gid, "mission",
                        f"{ix.user.display_name} created mission '{self.f_name.value.strip()}'")
        self.parent.sel_mid = mid
        self.parent._build()
        await ix.response.edit_message(view=self.parent)


# ── Mission Channels Config ───────────────────────────────────────────────────

class MissionChannelsView(LayoutView):
    def __init__(self, gid, mid, parent, guild):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent; self.guild = guild
        self._build()

    def _build(self):
        self.clear_items()
        db = load_missions(self.gid)
        m  = db.get("missions", {}).get(self.mid, {})

        post_names = [f"<#{c}>" for c in m.get("channels", [])]
        log_names  = [f"<#{c}>" for c in m.get("log_channels", [])]
        text = "\n".join([
            "**Mission Channel Configuration**",
            "",
            f"**Post channels:** {', '.join(post_names) or '*none*'}",
            f"**Log channels:** {', '.join(log_names) or '*none*'}",
        ])

        post_sel = discord.ui.ChannelSelect(
            placeholder="Add post channel",
            channel_types=[discord.ChannelType.text],
            custom_id="mch_post",
        )
        log_sel = discord.ui.ChannelSelect(
            placeholder="Add log channel",
            channel_types=[discord.ChannelType.text],
            custom_id="mch_log",
        )
        post_sel.callback = self._add_post
        log_sel.callback  = self._add_log

        clear_post = Button(label="Clear post channels", style=discord.ButtonStyle.danger, custom_id="mch_clrp")
        clear_log  = Button(label="Clear log channels",  style=discord.ButtonStyle.danger, custom_id="mch_clrl")
        bk_btn     = Button(label=t(self.gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="mch_bk")
        clear_post.callback = self._clear_post
        clear_log.callback  = self._clear_log
        bk_btn.callback     = self._back

        self.add_item(Container(
            ActionRow(bk_btn),
            Separator(),
            TextDisplay(text),
            Separator(),
            ActionRow(post_sel),
            ActionRow(log_sel),
            ActionRow(clear_post, clear_log),
        ))

    async def _add_post(self, ix):
        db = load_missions(self.gid)
        cid = str(ix.data["values"][0])
        m   = db["missions"].get(self.mid)
        if m and cid not in m.get("channels", []):
            m.setdefault("channels", []).append(cid)
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _add_log(self, ix):
        db = load_missions(self.gid)
        cid = str(ix.data["values"][0])
        m   = db["missions"].get(self.mid)
        if m and cid not in m.get("log_channels", []):
            m.setdefault("log_channels", []).append(cid)
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _clear_post(self, ix):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["channels"] = []
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _clear_log(self, ix):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["log_channels"] = []
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


# ── Mission Drops Config ──────────────────────────────────────────────────────

class MissionDropsView(LayoutView):
    def __init__(self, gid, mid, parent, page: int = 0):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent; self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        db = load_missions(self.gid)
        m  = db.get("missions", {}).items()
        drops = db.get("missions", {}).get(self.mid, {}).get("item_drops", {"all": [], "targeted": {}})

        lines = ["**🎁 Configure Item Drops**", ""]
        for drop in drops.get("all", [])[:5]:
            lines.append(f"All: {drop.get('item_name','?')} × {drop.get('qty',1)}")
        for uid, udrops in list(drops.get("targeted", {}).items())[:3]:
            for d in udrops[:2]:
                lines.append(f"→ <@{uid}>: {d.get('item_name','?')} × {d.get('qty',1)}")

        bk_btn      = Button(label=t(self.gid, "back_btn"),        style=discord.ButtonStyle.secondary, custom_id="md_bk")
        all_btn     = Button(label=t(self.gid, "drop_for_all_btn"),style=discord.ButtonStyle.primary,   custom_id="md_all")
        target_btn  = Button(label=t(self.gid, "drop_for_player_btn"), style=discord.ButtonStyle.secondary, custom_id="md_tgt")
        clear_btn   = Button(label="Clear All Drops",              style=discord.ButtonStyle.danger,    custom_id="md_clear")
        bk_btn.callback     = self._back
        all_btn.callback    = self._add_for_all
        target_btn.callback = self._add_for_target
        clear_btn.callback  = self._clear

        self.add_item(Container(
            ActionRow(bk_btn),
            Separator(),
            TextDisplay("\n".join(lines)),
            Separator(),
            ActionRow(all_btn, target_btn),
            ActionRow(clear_btn),
        ))

    async def _add_for_all(self, ix):
        await ix.response.send_modal(_DropModal(self.gid, self.mid, None, self))

    async def _add_for_target(self, ix):
        await ix.response.edit_message(view=_DropTargetSelectView(self.gid, self.mid, self))

    async def _clear(self, ix):
        db = load_missions(self.gid)
        if self.mid in db["missions"]:
            db["missions"][self.mid]["item_drops"] = {"all": [], "targeted": {}}
        save_missions(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class _DropTargetSelectView(LayoutView):
    def __init__(self, gid, mid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.mid = mid; self.parent = parent
        db = load_missions(gid)
        mission = db.get("missions", {}).get(mid, {})
        players = mission.get("players", {})
        opts = ([discord.SelectOption(
                     label=pdata.get("display_name", uid)[:100], value=uid)
                 for uid, pdata in list(players.items())[:25]]
                or [discord.SelectOption(label="No players", value="__none__")])
        sel = Select(placeholder="Select player for targeted drop", options=opts)
        sel.callback = self._sel
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="dts_bk")
        bk.callback = self._back
        self.add_item(Container(
            ActionRow(bk),
            Separator(),
            TextDisplay("**Select player for targeted drop:**"),
            ActionRow(sel),
        ))

    async def _sel(self, ix):
        uid = ix.data["values"][0]
        if uid == "__none__": await ix.response.defer(); return
        await ix.response.send_modal(_DropModal(self.gid, self.mid, uid, self.parent))

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class _DropModal(Modal, title="Add Item Drop"):
    f_item = TextInput(label="Item Name", max_length=60)
    f_qty  = TextInput(label="Quantity",  max_length=5, default="1")

    def __init__(self, gid, mid, target_uid, parent):
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
                m["item_drops"].setdefault("targeted", {}).setdefault(
                    self.target_uid, []).append(drop_data)
            else:
                m["item_drops"].setdefault("all", []).append(drop_data)
        save_missions(self.gid, db)
        self.parent._build()
        await ix.response.edit_message(view=self.parent)
        await ix.followup.send(t(self.gid, "mission_drop_added"), ephemeral=True)


# ── Finish Mission Modal ──────────────────────────────────────────────────────

class MissionLogModal(Modal, title="Mission Log"):
    f_log = TextInput(label="Mission Log",
                      style=discord.TextStyle.paragraph, max_length=2000)

    def __init__(self, gid, mid, parent):
        super().__init__()
        self.gid = gid; self.mid = mid; self.parent = parent
        self.f_log.label = t(gid, "mission_log_field")

    async def on_submit(self, ix: discord.Interaction):
        db  = load_missions(self.gid)
        m   = db["missions"].get(self.mid)
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
        await ix.response.edit_message(view=self.parent)
        await ix.followup.send(t(self.gid, "mission_completed", name=m["name"]), ephemeral=True)


async def _distribute_drops(gid: int, mission: dict, guild):
    players_db = load_players(gid)
    items_db   = load_items(gid)
    all_items  = items_db.get("items", {})
    drops      = mission.get("item_drops", {})

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
                    await cv2_dm(member, t(gid, "mission_drop_given",
                                           item=drop["item_name"], qty=qty))
        if changed:
            players_db[uid] = player
    save_players(gid, players_db)


async def _post_mission_log(gid: int, mission: dict, guild):
    if not guild:
        return
    player_list = []
    for uid, pdata in mission.get("players", {}).items():
        player_list.append(f"• {pdata.get('display_name', uid)}")

    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(mission.get("completed_at", time.time())))
    text = "\n".join([
        f"**📋 Mission Log — {mission['name']}**",
        f"*Completed: {ts}*",
        "",
        f"**Description:** {mission.get('description', '')}",
        "",
        f"**Participants ({len(player_list)}):**",
        *player_list[:20],
        "",
        f"**Log:**",
        mission.get("log_text", ""),
    ])

    import discord as _d
    v = _d.ui.LayoutView(timeout=None)
    v.add_item(_d.ui.Container(_d.ui.TextDisplay(text)))

    for ch_id in mission.get("log_channels", []):
        ch = guild.get_channel(int(ch_id))
        if ch:
            try:
                await ch.send(view=v)
            except Exception:
                pass
