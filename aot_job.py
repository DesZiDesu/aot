"""Job system — /job (player), /job-owner (owner), /job-admin (admin)."""
import time, uuid
import discord
from discord import app_commands
from discord.ext import tasks
from discord.ui import (LayoutView, Container, TextDisplay, Separator,
                        ActionRow, Button, Select, Modal, TextInput)

from aot_bot_instance import bot
from aot_shared import (
    t, load_config, load_players, save_players,
    load_jobs, save_jobs, format_currency, cv2_dm, log_event,
)

_PER_PAGE = 8


def _is_admin():
    async def pred(ix: discord.Interaction) -> bool:
        if not ix.guild: return False
        m = ix.guild.get_member(ix.user.id)
        return m is not None and (m.guild_permissions.administrator or m.guild_permissions.manage_guild)
    return app_commands.check(pred)


# ── Background tasks ──────────────────────────────────────────────────────────

@tasks.loop(minutes=1)
async def passive_income_task():
    now = time.time()
    for guild in bot.guilds:
        gid     = guild.id
        db      = load_jobs(gid)
        players = load_players(gid)
        changed = False
        for job in db.get("jobs", {}).values():
            if not job.get("active") or job.get("mode") != "passive":
                continue
            interval = job.get("passive_interval_seconds", 3600)
            reward   = job.get("passive_reward", 0)
            if interval <= 0 or reward <= 0:
                continue
            for uid in list(job.get("employees", {}).keys()):
                emp = job["employees"][uid]
                last = emp.get("last_passive_earned", 0)
                if now - last >= interval:
                    player = players.get(uid, {})
                    if not player:
                        continue
                    player["balance"] = player.get("balance", 0) + reward
                    players[uid] = player
                    emp["last_passive_earned"] = now
                    changed = True
                    member = guild.get_member(int(uid))
                    if member:
                        await cv2_dm(member, t(gid, "job_passive_earned",
                                               job=job["name"], amount=reward))
        if changed:
            save_players(gid, players)
            save_jobs(gid, db)


def start_job_tasks():
    if not passive_income_task.is_running():
        passive_income_task.start()


# ── on_message for RP job mode ────────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    gid = message.guild.id
    db  = load_jobs(gid)
    uid = str(message.author.id)
    now = time.time()
    changed = False
    players = None

    for job in db.get("jobs", {}).values():
        if not job.get("active") or job.get("mode") != "rp":
            continue
        if uid not in job.get("employees", {}):
            continue
        rp_ch = job.get("rp_channel_id")
        if not rp_ch or str(message.channel.id) != str(rp_ch):
            continue
        min_letters = job.get("rp_min_letters", 50)
        if len(message.content) < min_letters:
            continue
        cooldown = job.get("rp_cooldown_seconds", 3600)
        emp      = job["employees"][uid]
        last     = emp.get("last_rp_earned", 0)
        if now - last < cooldown:
            continue
        if players is None:
            players = load_players(gid)
        player = players.get(uid, {})
        if not player:
            continue
        reward = job.get("rp_reward", 0)
        player["balance"] = player.get("balance", 0) + reward
        players[uid]      = player
        emp["last_rp_earned"] = now
        changed = True
        await cv2_dm(message.author,
                     t(gid, "job_rp_earned", job=job["name"], amount=reward))

    if changed:
        save_players(gid, players)
        save_jobs(gid, db)


# ── /job (player browse & apply) ─────────────────────────────────────────────

class JobListView(LayoutView):
    def __init__(self, gid: int, uid: int, page: int = 0):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid; self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        db   = load_jobs(self.gid)
        jobs = [(jid, j) for jid, j in db.get("jobs", {}).items() if j.get("active")]

        total_pages = max(1, (len(jobs) + _PER_PAGE - 1) // _PER_PAGE)
        self.page   = max(0, min(self.page, total_pages - 1))
        chunk = jobs[self.page * _PER_PAGE:(self.page + 1) * _PER_PAGE]

        lines = [f"**{t(self.gid,'job_title')}**", ""]
        if not chunk:
            lines.append(t(self.gid, "no_jobs"))

        job_rows = []
        for jid, j in chunk:
            mode_icon = "📝" if j.get("mode") == "rp" else "💤"
            applied   = str(self.uid) in j.get("applicants", {})
            employed  = str(self.uid) in j.get("employees", {})
            status    = "✅ Employed" if employed else ("⏳ Applied" if applied else "")
            lines.append(f"**{j['name']}** {mode_icon} {status}")
            lines.append(f"*{j.get('description','')[:80]}*")
            lines.append(f"Owner: {j.get('owner_name','?')} | Reward: {j.get('rp_reward' if j.get('mode')=='rp' else 'passive_reward',0)}")
            lines.append("")

            can_apply = not applied and not employed
            ab = Button(label=t(self.gid, "apply_job_btn"),
                        style=discord.ButtonStyle.green if can_apply else discord.ButtonStyle.secondary,
                        custom_id=f"jl_apply_{jid}", disabled=not can_apply)
            ab.callback = self._make_apply(jid, j["name"])
            job_rows.append(ActionRow(ab))

        prev_btn = Button(label=t(self.gid, "prev_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="jl_prev", disabled=(self.page == 0))
        next_btn = Button(label=t(self.gid, "next_btn"), style=discord.ButtonStyle.secondary,
                          custom_id="jl_next", disabled=(self.page >= total_pages - 1))
        done_btn = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger,
                          custom_id="jl_done")
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        done_btn.callback = self._done

        self.add_item(Container(
            TextDisplay("\n".join(lines)),
            Separator(),
            *job_rows,
            Separator(),
            ActionRow(prev_btn, next_btn),
            ActionRow(done_btn),
        ))

    def _make_apply(self, jid, jname):
        async def _apply(ix: discord.Interaction):
            players = load_players(self.gid)
            player  = players.get(str(self.uid), {})
            db      = load_jobs(self.gid)
            job     = db.get("jobs", {}).get(jid)
            if not job:
                await ix.response.send_message("Job not found.", ephemeral=True); return
            if str(self.uid) in job.get("applicants", {}):
                await ix.response.send_message(
                    t(self.gid, "already_joined_mission"), ephemeral=True); return
            char_name = player.get("name", ix.user.display_name)
            job.setdefault("applicants", {})[str(self.uid)] = {
                "applied_at": time.time(),
                "status":     "pending",
                "char_name":  char_name,
                "display_name": ix.user.display_name,
            }
            save_jobs(self.gid, db)
            await log_event(bot, self.gid, "job",
                            f"{ix.user.display_name} applied for job '{jname}'")
            owner_id = job.get("owner_id")
            if owner_id:
                for g in bot.guilds:
                    if g.id == self.gid:
                        member = g.get_member(int(owner_id))
                        if member:
                            await cv2_dm(member, t(self.gid, "job_notify_owner",
                                                   user=ix.user.display_name,
                                                   char=char_name, job=jname))
                        break
            await ix.response.send_message(
                t(self.gid, "job_applied", name=jname), ephemeral=True)
            self._build(); await ix.edit_original_response(view=self)
        return _apply

    async def _prev(self, ix): self.page -= 1; self._build(); await ix.response.edit_message(view=self)
    async def _next(self, ix): self.page += 1; self._build(); await ix.response.edit_message(view=self)
    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


@bot.tree.command(name="job", description="Browse and apply for jobs",
                  description_localizations={"th": "ดูงานและสมัครงาน"})
async def job_cmd(ix: discord.Interaction):
    await ix.response.send_message(view=JobListView(ix.guild_id, ix.user.id), ephemeral=True)


# ── /job-owner ────────────────────────────────────────────────────────────────

class JobOwnerView(LayoutView):
    def __init__(self, gid: int, uid: int):
        super().__init__(timeout=300)
        self.gid = gid; self.uid = uid
        self.sel_job  = None
        self.sel_applicant = None
        self._build()

    def _build(self):
        self.clear_items()
        db   = load_jobs(self.gid)
        mine = [(jid, j) for jid, j in db.get("jobs", {}).items()
                if str(j.get("owner_id")) == str(self.uid) and j.get("active")]

        if not mine:
            done_btn = Button(label=t(self.gid, "done_btn"),
                              style=discord.ButtonStyle.danger, custom_id="jo_done")
            done_btn.callback = self._done
            self.add_item(Container(
                TextDisplay(f"**{t(self.gid,'job_owner_title')}**\n\nNo jobs owned."),
                ActionRow(done_btn),
            ))
            return

        job_opts = [discord.SelectOption(label=j["name"][:100], value=jid,
                                          default=(jid == self.sel_job))
                    for jid, j in mine[:25]]
        job_sel = Select(placeholder="Select your job", options=job_opts)
        job_sel.callback = self._sel_job

        children = [TextDisplay(f"**{t(self.gid,'job_owner_title')}**"), Separator(), ActionRow(job_sel)]

        if self.sel_job:
            job   = db["jobs"].get(self.sel_job, {})
            pend  = [(uid, a) for uid, a in job.get("applicants", {}).items()
                     if a.get("status") == "pending"]
            if pend:
                app_opts = [discord.SelectOption(
                    label=f"{a['display_name']} ({a['char_name']})".ljust(1)[:100],
                    value=uid,
                    default=(uid == self.sel_applicant))
                    for uid, a in pend[:25]]
                app_sel = Select(placeholder=t(self.gid, "select_applicant"), options=app_opts)
                app_sel.callback = self._sel_applicant
                children += [Separator(), TextDisplay(f"**Pending applicants:** {len(pend)}"), ActionRow(app_sel)]
                if self.sel_applicant:
                    accept_btn = Button(label=t(self.gid, "approve_btn"),
                                        style=discord.ButtonStyle.green, custom_id="jo_accept")
                    decline_btn = Button(label=t(self.gid, "decline_btn"),
                                         style=discord.ButtonStyle.danger, custom_id="jo_decline")
                    accept_btn.callback  = self._accept
                    decline_btn.callback = self._decline
                    children.append(ActionRow(accept_btn, decline_btn))
            else:
                children.append(TextDisplay(t(self.gid, "no_applicants")))

        done_btn = Button(label=t(self.gid, "done_btn"), style=discord.ButtonStyle.danger, custom_id="jo_done")
        done_btn.callback = self._done
        children.append(ActionRow(done_btn))
        self.add_item(Container(*children))

    async def _sel_job(self, ix):
        v = ix.data["values"][0]
        self.sel_job = v; self.sel_applicant = None
        self._build(); await ix.response.edit_message(view=self)

    async def _sel_applicant(self, ix):
        self.sel_applicant = ix.data["values"][0]
        self._build(); await ix.response.edit_message(view=self)

    async def _accept(self, ix: discord.Interaction):
        db  = load_jobs(self.gid)
        job = db["jobs"].get(self.sel_job, {})
        app = job.get("applicants", {}).get(self.sel_applicant, {})
        app["status"] = "accepted"
        job.setdefault("employees", {})[self.sel_applicant] = {
            "hired_at": time.time(), "last_rp_earned": 0, "last_passive_earned": 0
        }
        save_jobs(self.gid, db)
        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(self.sel_applicant))
                if member:
                    await cv2_dm(member, t(self.gid, "job_accepted", name=job["name"]))
                break
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} accepted {app.get('display_name','?')} for job '{job['name']}'")
        self.sel_applicant = None
        self._build(); await ix.response.edit_message(view=self)

    async def _decline(self, ix: discord.Interaction):
        db  = load_jobs(self.gid)
        job = db["jobs"].get(self.sel_job, {})
        app = job.get("applicants", {}).get(self.sel_applicant, {})
        app["status"] = "declined"
        save_jobs(self.gid, db)
        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(self.sel_applicant))
                if member:
                    await cv2_dm(member, t(self.gid, "job_declined", name=job["name"]))
                break
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} declined {app.get('display_name','?')} for job '{job['name']}'")
        self.sel_applicant = None
        self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


@bot.tree.command(name="job-owner",
                  description="Manage your job applicants",
                  description_localizations={"th": "จัดการผู้สมัครงานของคุณ"})
async def job_owner_cmd(ix: discord.Interaction):
    await ix.response.send_message(view=JobOwnerView(ix.guild_id, ix.user.id), ephemeral=True)


# ── /job-admin ────────────────────────────────────────────────────────────────

class JobAdminView(LayoutView):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid; self.sel_job = None
        self._build()

    def _build(self):
        self.clear_items()
        db   = load_jobs(self.gid)
        jobs = db.get("jobs", {})

        opts = ([discord.SelectOption(label=f"{'✅' if j.get('active') else '❌'} {j['name'][:90]}", value=jid,
                                       default=(jid == self.sel_job))
                 for jid, j in list(jobs.items())[:25]]
                or [discord.SelectOption(label="No jobs", value="__none__")])
        sel = Select(placeholder="Select job to manage", options=opts)
        sel.callback = self._sel

        create_btn = Button(label=t(self.gid, "create_job_btn"),
                            style=discord.ButtonStyle.green, custom_id="ja_create")
        done_btn   = Button(label=t(self.gid, "done_btn"),
                            style=discord.ButtonStyle.danger, custom_id="ja_done")
        create_btn.callback = self._create
        done_btn.callback   = self._done

        children = [TextDisplay(f"**{t(self.gid,'job_admin_title')}**"), Separator(), ActionRow(sel)]

        if self.sel_job and self.sel_job in jobs:
            j = jobs[self.sel_job]
            emp_count = len(j.get("employees", {}))
            app_count = sum(1 for a in j.get("applicants", {}).values() if a.get("status") == "pending")
            mode_str  = j.get("mode", "rp")
            info = "\n".join([
                f"**{j['name']}** ({'Active' if j.get('active') else 'Inactive'})",
                f"Mode: {mode_str} | Owner: {j.get('owner_name','?')}",
                f"Employees: {emp_count} | Pending applicants: {app_count}",
                f"Reward: {j.get('rp_reward' if mode_str=='rp' else 'passive_reward', 0)}",
            ])
            edit_btn     = Button(label="Edit Job",           style=discord.ButtonStyle.primary, custom_id="ja_edit")
            toggle_btn   = Button(label="Deactivate" if j.get("active") else "Activate",
                                  style=discord.ButtonStyle.secondary, custom_id="ja_toggle")
            fire_btn     = Button(label=t(self.gid, "fire_employee_btn"),
                                  style=discord.ButtonStyle.danger, custom_id="ja_fire")
            del_btn      = Button(label="Delete Job",         style=discord.ButtonStyle.danger, custom_id="ja_del")
            edit_btn.callback   = self._edit
            toggle_btn.callback = self._toggle
            fire_btn.callback   = self._fire
            del_btn.callback    = self._delete
            children += [Separator(), TextDisplay(info),
                         ActionRow(edit_btn, toggle_btn),
                         ActionRow(fire_btn, del_btn)]

        children.append(ActionRow(create_btn, done_btn))
        self.add_item(Container(*children))

    async def _sel(self, ix):
        v = ix.data["values"][0]; self.sel_job = v if v != "__none__" else None
        self._build(); await ix.response.edit_message(view=self)

    async def _create(self, ix):
        await ix.response.send_modal(CreateJobModal(self.gid, self))

    async def _edit(self, ix):
        db = load_jobs(self.gid)
        j  = db["jobs"].get(self.sel_job, {})
        await ix.response.send_modal(EditJobModal(self.gid, self.sel_job, j, self))

    async def _toggle(self, ix):
        db = load_jobs(self.gid)
        j  = db["jobs"].get(self.sel_job, {})
        j["active"] = not j.get("active", True)
        save_jobs(self.gid, db)
        self._build(); await ix.response.edit_message(view=self)

    async def _fire(self, ix):
        await ix.response.edit_message(view=FireEmployeeView(self.gid, self.sel_job, self))

    async def _delete(self, ix):
        db = load_jobs(self.gid); db["jobs"].pop(self.sel_job, None)
        save_jobs(self.gid, db); self.sel_job = None
        self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix):
        self.clear_items()
        self.add_item(Container(TextDisplay(f"*{t(self.gid,'panel_closed')}*")))
        await ix.response.edit_message(view=self)


class FireEmployeeView(LayoutView):
    def __init__(self, gid, jid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.jid = jid; self.parent = parent
        db  = load_jobs(gid)
        job = db.get("jobs", {}).get(jid, {})
        emps = job.get("employees", {})
        opts = ([discord.SelectOption(
                     label=f"<@{uid}> hired {time.strftime('%m/%d', time.localtime(e.get('hired_at',0)))}",
                     value=uid)
                 for uid, e in list(emps.items())[:25]]
                or [discord.SelectOption(label="No employees", value="__none__")])
        sel = Select(placeholder="Select employee to fire", options=opts)
        sel.callback = self._fire
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="fe_bk")
        bk.callback = self._back
        self.add_item(Container(ActionRow(bk), Separator(),
                                TextDisplay("**Select employee to fire:**"), ActionRow(sel)))

    async def _fire(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        if uid == "__none__": await ix.response.defer(); return
        db  = load_jobs(self.gid)
        job = db["jobs"].get(self.jid, {})
        job.get("employees", {}).pop(uid, None)
        save_jobs(self.gid, db)
        for g in bot.guilds:
            if g.id == self.gid:
                member = g.get_member(int(uid))
                if member:
                    await cv2_dm(member, t(self.gid, "job_fired", job=job["name"]))
                break
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class CreateJobModal(Modal, title="Create Job"):
    f_name  = TextInput(label="Job Name",    max_length=60)
    f_owner = TextInput(label="Owner Name",  max_length=60)
    f_desc  = TextInput(label="Description", style=discord.TextStyle.paragraph,
                        max_length=300, required=False)
    f_owner_id = TextInput(label="Owner Discord User ID (optional)", max_length=20, required=False)

    def __init__(self, gid, parent):
        super().__init__(); self.gid = gid; self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        jid = str(uuid.uuid4())[:8]
        db  = load_jobs(self.gid)
        db["jobs"][jid] = {
            "id": jid,
            "name":                   self.f_name.value.strip(),
            "description":            (self.f_desc.value or "").strip(),
            "owner_name":             self.f_owner.value.strip(),
            "owner_id":               (self.f_owner_id.value or "").strip() or None,
            "mode":                   "rp",
            "rp_channel_id":          None,
            "rp_min_letters":         50,
            "rp_cooldown_seconds":    3600,
            "rp_reward":              100,
            "passive_reward":         30,
            "passive_interval_seconds": 3600,
            "applicants":             {},
            "employees":              {},
            "active":                 True,
        }
        save_jobs(self.gid, db)
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} created job '{self.f_name.value.strip()}'")
        self.parent.sel_job = jid
        self.parent._build(); await ix.response.edit_message(view=self.parent)
        await ix.followup.send(t(self.gid, "job_created", name=self.f_name.value.strip()), ephemeral=True)


class EditJobModal(Modal, title="Edit Job"):
    f_mode     = TextInput(label="Mode (rp / passive)",       max_length=10)
    f_min_let  = TextInput(label="Min letters (RP mode)",     max_length=5)
    f_cooldown = TextInput(label="RP cooldown (seconds)",     max_length=8)
    f_reward   = TextInput(label="RP reward per round",       max_length=8)
    f_p_interval = TextInput(label="Passive interval (seconds)", max_length=8)

    def __init__(self, gid, jid, job, parent):
        super().__init__(); self.gid = gid; self.jid = jid; self.parent = parent
        self.f_mode.default       = job.get("mode", "rp")
        self.f_min_let.default    = str(job.get("rp_min_letters", 50))
        self.f_cooldown.default   = str(job.get("rp_cooldown_seconds", 3600))
        self.f_reward.default     = str(job.get("rp_reward", 100))
        self.f_p_interval.default = str(job.get("passive_interval_seconds", 3600))

    async def on_submit(self, ix: discord.Interaction):
        db  = load_jobs(self.gid)
        job = db["jobs"].get(self.jid, {})
        mode = self.f_mode.value.strip().lower()
        if mode not in ("rp", "passive"):
            mode = "rp"
        def _int(v, d):
            try: return max(0, int(v.strip()))
            except: return d
        job["mode"]                   = mode
        job["rp_min_letters"]         = _int(self.f_min_let.value, 50)
        job["rp_cooldown_seconds"]    = _int(self.f_cooldown.value, 3600)
        job["rp_reward"]              = _int(self.f_reward.value, 100)
        job["passive_interval_seconds"] = _int(self.f_p_interval.value, 3600)
        save_jobs(self.gid, db)
        self.parent._build(); await ix.response.edit_message(view=self.parent)


class _SetRPChannelView(LayoutView):
    def __init__(self, gid, jid, parent):
        super().__init__(timeout=300)
        self.gid = gid; self.jid = jid; self.parent = parent
        ch_sel = discord.ui.ChannelSelect(
            placeholder="Select RP channel",
            channel_types=[discord.ChannelType.text],
        )
        ch_sel.callback = self._pick
        bk = Button(label=t(gid, "back_btn"), style=discord.ButtonStyle.secondary, custom_id="src_bk")
        bk.callback = self._back
        self.add_item(Container(ActionRow(bk), Separator(),
                                TextDisplay("**Select RP earning channel:**"), ActionRow(ch_sel)))

    async def _pick(self, ix):
        db  = load_jobs(self.gid)
        job = db["jobs"].get(self.jid, {})
        job["rp_channel_id"] = str(ix.data["values"][0])
        save_jobs(self.gid, db)
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(view=self.parent)


@bot.tree.command(name="job-admin",
                  description="Admin job management panel",
                  description_localizations={"th": "แผงจัดการงานสำหรับแอดมิน"})
@_is_admin()
async def job_admin_cmd(ix: discord.Interaction):
    await ix.response.send_message(view=JobAdminView(ix.guild_id), ephemeral=True)

@job_admin_cmd.error
async def job_admin_error(ix, error):
    await ix.response.send_message(t(ix.guild_id, "admin_only"), ephemeral=True)
