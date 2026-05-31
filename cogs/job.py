"""Job system — /job (player), /job-owner (owner), /job-admin (admin).

Uses discord.Embed + discord.ui.View only (no Components V2).
"""
import time
import uuid

import discord
from discord import app_commands
from discord.ext import tasks
from discord.ui import Modal, TextInput

from core.instance import bot
from core.shared import (
    EMBED_COLOR,
    format_currency,
    load_config,
    load_jobs,
    load_players,
    log_event,
    save_jobs,
    save_players,
    t,
)

_PER_PAGE = 8


# ── Permission helper ─────────────────────────────────────────────────────────

def _member_is_admin(member: discord.Member) -> bool:
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


# ── Background task: passive income ──────────────────────────────────────────

@tasks.loop(seconds=60)
async def passive_income_task():
    now = time.time()
    for guild in bot.guilds:
        gid = guild.id
        db = load_jobs(gid)
        players = load_players(gid)
        changed = False
        for job in db.get("jobs", {}).values():
            if not job.get("active") or job.get("mode") != "passive":
                continue
            interval = job.get("passive_interval_seconds", 3600)
            reward = job.get("passive_reward", 0)
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
                        try:
                            dm = await member.create_dm()
                            embed = discord.Embed(
                                description=t(gid, "job_passive_earned",
                                              job=job["name"], amount=reward),
                                color=EMBED_COLOR,
                            )
                            await dm.send(embed=embed)
                        except Exception:
                            pass
        if changed:
            save_players(gid, players)
            save_jobs(gid, db)


def start_job_tasks():
    if not passive_income_task.is_running():
        passive_income_task.start()


# ── on_message: RP income ─────────────────────────────────────────────────────

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    gid = message.guild.id
    db = load_jobs(gid)
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
        emp = job["employees"][uid]
        last = emp.get("last_rp_earned", 0)
        if now - last < cooldown:
            continue
        if players is None:
            players = load_players(gid)
        player = players.get(uid, {})
        if not player:
            continue
        reward = job.get("rp_reward", 0)
        player["balance"] = player.get("balance", 0) + reward
        players[uid] = player
        emp["last_rp_earned"] = now
        changed = True
        try:
            dm = await message.author.create_dm()
            embed = discord.Embed(
                description=t(gid, "job_rp_earned",
                              job=job["name"], amount=reward),
                color=EMBED_COLOR,
            )
            await dm.send(embed=embed)
        except Exception:
            pass

    if changed:
        save_players(gid, players)
        save_jobs(gid, db)


# ── /job — Player browse & apply ──────────────────────────────────────────────

def _build_job_list(gid: int, uid: int, page: int = 0):
    """Return (embed, JobListView)."""
    db = load_jobs(gid)
    jobs = [(jid, j) for jid, j in db.get("jobs", {}).items() if j.get("active")]
    total_pages = max(1, (len(jobs) + _PER_PAGE - 1) // _PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    chunk = jobs[page * _PER_PAGE:(page + 1) * _PER_PAGE]

    embed = discord.Embed(title=t(gid, "job_title"), color=EMBED_COLOR)
    embed.set_footer(text=t(gid, "page_label", page=page + 1, total=total_pages))

    if not chunk:
        embed.description = t(gid, "no_jobs")
    else:
        for jid, j in chunk:
            mode_icon = "📝" if j.get("mode") == "rp" else "💤"
            applied = str(uid) in j.get("applicants", {})
            employed = str(uid) in j.get("employees", {})
            status = " ✅ Employed" if employed else (" ⏳ Applied" if applied else "")
            reward = j.get("rp_reward" if j.get("mode") == "rp" else "passive_reward", 0)
            embed.add_field(
                name=f"{mode_icon} {j['name']}{status}",
                value=(
                    f"*{j.get('description', '')[:100]}*\n"
                    f"Owner: **{j.get('owner_name', '?')}** | "
                    f"Reward: **{reward}**"
                ),
                inline=False,
            )

    view = JobListView(gid=gid, uid=uid, page=page,
                       chunk=chunk, total_pages=total_pages)
    return embed, view


class JobListView(discord.ui.View):
    def __init__(self, gid: int, uid: int, page: int,
                 chunk: list, total_pages: int):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.page = page
        self.total_pages = total_pages

        # Row 0: Done
        done_btn = discord.ui.Button(
            label=t(gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="jl_done",
            row=0,
        )
        done_btn.callback = self._done
        self.add_item(done_btn)

        # Row 1: Apply select
        if chunk:
            opts = []
            for jid, j in chunk:
                applied = str(uid) in j.get("applicants", {})
                employed = str(uid) in j.get("employees", {})
                desc = "Employed" if employed else ("Applied" if applied else "Available")
                opts.append(discord.SelectOption(
                    label=j["name"][:100],
                    value=jid,
                    description=desc[:100],
                ))
            apply_sel = discord.ui.Select(
                placeholder=t(gid, "apply_job_btn"),
                options=opts,
                custom_id="jl_apply_sel",
                row=1,
            )
            apply_sel.callback = self._apply_selected
            self.add_item(apply_sel)

        # Row 2: Pagination
        prev_btn = discord.ui.Button(
            label=t(gid, "prev_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="jl_prev",
            disabled=(page == 0),
            row=2,
        )
        next_btn = discord.ui.Button(
            label=t(gid, "next_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="jl_next",
            disabled=(page >= total_pages - 1),
            row=2,
        )
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        self.add_item(prev_btn)
        self.add_item(next_btn)

    async def _apply_selected(self, ix: discord.Interaction):
        jid = ix.data["values"][0]
        players = load_players(self.gid)
        player = players.get(str(self.uid), {})
        db = load_jobs(self.gid)
        job = db.get("jobs", {}).get(jid)
        if not job:
            await ix.response.send_message("Job not found.", ephemeral=True)
            return
        if str(self.uid) in job.get("applicants", {}):
            await ix.response.send_message(
                t(self.gid, "already_joined_mission"), ephemeral=True)
            return
        if str(self.uid) in job.get("employees", {}):
            await ix.response.send_message("Already employed here.", ephemeral=True)
            return
        char_name = player.get("name", ix.user.display_name)
        job.setdefault("applicants", {})[str(self.uid)] = {
            "applied_at": time.time(),
            "status": "pending",
            "char_name": char_name,
            "display_name": ix.user.display_name,
        }
        save_jobs(self.gid, db)
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} applied for job '{job['name']}'")

        # DM job owner
        owner_id = job.get("owner_id")
        if owner_id and ix.guild:
            member = ix.guild.get_member(int(owner_id))
            if member:
                try:
                    dm = await member.create_dm()
                    notify_embed = discord.Embed(
                        description=t(self.gid, "job_notify_owner",
                                      user=ix.user.display_name,
                                      char=char_name, job=job["name"]),
                        color=EMBED_COLOR,
                    )
                    await dm.send(embed=notify_embed)
                except Exception:
                    pass

        embed, view = _build_job_list(self.gid, self.uid, self.page)
        await ix.response.edit_message(embed=embed, view=view)
        await ix.followup.send(
            t(self.gid, "job_applied", name=job["name"]), ephemeral=True)

    async def _prev(self, ix: discord.Interaction):
        embed, view = _build_job_list(self.gid, self.uid, self.page - 1)
        await ix.response.edit_message(embed=embed, view=view)

    async def _next(self, ix: discord.Interaction):
        embed, view = _build_job_list(self.gid, self.uid, self.page + 1)
        await ix.response.edit_message(embed=embed, view=view)

    async def _done(self, ix: discord.Interaction):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=None)


@bot.tree.command(
    name="job",
    description="Browse and apply for jobs",
    description_localizations={"th": "ดูงานและสมัครงาน"},
)
async def job_cmd(ix: discord.Interaction):
    embed, view = _build_job_list(ix.guild_id, ix.user.id, page=0)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── /job-owner ────────────────────────────────────────────────────────────────

def _build_job_owner(gid: int, uid: int, sel_job: str = None,
                     sel_applicant: str = None):
    """Return (embed, JobOwnerView)."""
    db = load_jobs(gid)
    mine = [(jid, j) for jid, j in db.get("jobs", {}).items()
            if str(j.get("owner_id")) == str(uid) and j.get("active")]

    embed = discord.Embed(title=t(gid, "job_owner_title"), color=EMBED_COLOR)

    if not mine:
        embed.description = "No jobs owned."
        view = _SimpleDoneView(gid)
        return embed, view

    if sel_job:
        job = db["jobs"].get(sel_job, {})
        pend = [(u, a) for u, a in job.get("applicants", {}).items()
                if a.get("status") == "pending"]
        emp_count = len(job.get("employees", {}))
        embed.add_field(
            name=job.get("name", sel_job),
            value=f"Employees: **{emp_count}** | Pending: **{len(pend)}**",
            inline=False,
        )
        if pend:
            embed.add_field(
                name="Pending Applicants",
                value="\n".join(
                    f"• {a['display_name']} ({a['char_name']})"
                    for _, a in pend[:10]
                ),
                inline=False,
            )
        if job.get("employees"):
            embed.add_field(
                name="Current Employees",
                value="\n".join(
                    f"• <@{u}>" for u in list(job["employees"].keys())[:10]
                ),
                inline=False,
            )

    view = JobOwnerView(gid=gid, uid=uid, mine=mine, db=db,
                        sel_job=sel_job, sel_applicant=sel_applicant)
    return embed, view


class _SimpleDoneView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=120)
        self.gid = gid
        btn = discord.ui.Button(
            label=t(gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="sdv_done",
            row=0,
        )
        btn.callback = self._done
        self.add_item(btn)

    async def _done(self, ix: discord.Interaction):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=None)


class JobOwnerView(discord.ui.View):
    def __init__(self, gid: int, uid: int, mine: list, db: dict,
                 sel_job: str = None, sel_applicant: str = None):
        super().__init__(timeout=300)
        self.gid = gid
        self.uid = uid
        self.sel_job = sel_job
        self.sel_applicant = sel_applicant

        # Row 0: select job
        job_opts = [
            discord.SelectOption(label=j["name"][:100], value=jid,
                                  default=(jid == sel_job))
            for jid, j in mine[:25]
        ]
        job_sel = discord.ui.Select(
            placeholder="Select your job",
            options=job_opts,
            custom_id="jo_job_sel",
            row=0,
        )
        job_sel.callback = self._sel_job
        self.add_item(job_sel)

        if sel_job:
            job = db["jobs"].get(sel_job, {})
            pend = [(u, a) for u, a in job.get("applicants", {}).items()
                    if a.get("status") == "pending"]

            # Row 1: select applicant (if any)
            if pend:
                app_opts = [
                    discord.SelectOption(
                        label=f"{a['display_name']} ({a['char_name']})"[:100],
                        value=u,
                        default=(u == sel_applicant),
                    )
                    for u, a in pend[:25]
                ]
                app_sel = discord.ui.Select(
                    placeholder=t(gid, "select_applicant"),
                    options=app_opts,
                    custom_id="jo_app_sel",
                    row=1,
                )
                app_sel.callback = self._sel_applicant
                self.add_item(app_sel)

            # Row 2: Accept / Decline (shown when applicant selected)
            if sel_applicant:
                accept_btn = discord.ui.Button(
                    label=t(gid, "approve_btn"),
                    style=discord.ButtonStyle.green,
                    custom_id="jo_accept",
                    row=2,
                )
                decline_btn = discord.ui.Button(
                    label=t(gid, "decline_btn"),
                    style=discord.ButtonStyle.danger,
                    custom_id="jo_decline",
                    row=2,
                )
                accept_btn.callback = self._accept
                decline_btn.callback = self._decline
                self.add_item(accept_btn)
                self.add_item(decline_btn)

            # Row 3: Fire employee select
            emps = job.get("employees", {})
            if emps:
                fire_opts = [
                    discord.SelectOption(
                        label=f"<@{u}>".replace("<@", "").replace(">", "")[:80],
                        value=u,
                        description=f"Hired {time.strftime('%m/%d', time.localtime(e.get('hired_at', 0)))}",
                    )
                    for u, e in list(emps.items())[:25]
                ]
                fire_sel = discord.ui.Select(
                    placeholder=t(gid, "fire_employee_btn"),
                    options=fire_opts,
                    custom_id="jo_fire_sel",
                    row=3,
                )
                fire_sel.callback = self._fire
                self.add_item(fire_sel)

        # Row 4: Done
        done_btn = discord.ui.Button(
            label=t(gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="jo_done",
            row=4,
        )
        done_btn.callback = self._done
        self.add_item(done_btn)

    async def _sel_job(self, ix: discord.Interaction):
        jid = ix.data["values"][0]
        embed, view = _build_job_owner(self.gid, self.uid,
                                        sel_job=jid, sel_applicant=None)
        await ix.response.edit_message(embed=embed, view=view)

    async def _sel_applicant(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        embed, view = _build_job_owner(self.gid, self.uid,
                                        sel_job=self.sel_job, sel_applicant=uid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _accept(self, ix: discord.Interaction):
        db = load_jobs(self.gid)
        job = db["jobs"].get(self.sel_job, {})
        app = job.get("applicants", {}).get(self.sel_applicant, {})
        app["status"] = "accepted"
        job.setdefault("employees", {})[self.sel_applicant] = {
            "hired_at": time.time(),
            "last_rp_earned": 0,
            "last_passive_earned": 0,
        }
        save_jobs(self.gid, db)
        if ix.guild:
            member = ix.guild.get_member(int(self.sel_applicant))
            if member:
                try:
                    dm = await member.create_dm()
                    acc_embed = discord.Embed(
                        description=t(self.gid, "job_accepted", name=job["name"]),
                        color=EMBED_COLOR,
                    )
                    await dm.send(embed=acc_embed)
                except Exception:
                    pass
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} accepted "
                        f"{app.get('display_name', '?')} for job '{job['name']}'")
        embed, view = _build_job_owner(self.gid, self.uid,
                                        sel_job=self.sel_job, sel_applicant=None)
        await ix.response.edit_message(embed=embed, view=view)

    async def _decline(self, ix: discord.Interaction):
        db = load_jobs(self.gid)
        job = db["jobs"].get(self.sel_job, {})
        app = job.get("applicants", {}).get(self.sel_applicant, {})
        app["status"] = "declined"
        save_jobs(self.gid, db)
        if ix.guild:
            member = ix.guild.get_member(int(self.sel_applicant))
            if member:
                try:
                    dm = await member.create_dm()
                    dec_embed = discord.Embed(
                        description=t(self.gid, "job_declined", name=job["name"]),
                        color=EMBED_COLOR,
                    )
                    await dm.send(embed=dec_embed)
                except Exception:
                    pass
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} declined "
                        f"{app.get('display_name', '?')} for job '{job['name']}'")
        embed, view = _build_job_owner(self.gid, self.uid,
                                        sel_job=self.sel_job, sel_applicant=None)
        await ix.response.edit_message(embed=embed, view=view)

    async def _fire(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        db = load_jobs(self.gid)
        job = db["jobs"].get(self.sel_job, {})
        job.get("employees", {}).pop(uid, None)
        save_jobs(self.gid, db)
        if ix.guild:
            member = ix.guild.get_member(int(uid))
            if member:
                try:
                    dm = await member.create_dm()
                    fire_embed = discord.Embed(
                        description=t(self.gid, "job_fired", job=job["name"]),
                        color=EMBED_COLOR,
                    )
                    await dm.send(embed=fire_embed)
                except Exception:
                    pass
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} fired <@{uid}> from '{job['name']}'")
        embed, view = _build_job_owner(self.gid, self.uid,
                                        sel_job=self.sel_job, sel_applicant=None)
        await ix.response.edit_message(embed=embed, view=view)

    async def _done(self, ix: discord.Interaction):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=None)


@bot.tree.command(
    name="job-owner",
    description="Manage your job applicants and employees",
    description_localizations={"th": "จัดการผู้สมัครและพนักงานของคุณ"},
)
async def job_owner_cmd(ix: discord.Interaction):
    db = load_jobs(ix.guild_id)
    mine = [(jid, j) for jid, j in db.get("jobs", {}).items()
            if str(j.get("owner_id")) == str(ix.user.id) and j.get("active")]
    embed, view = _build_job_owner(ix.guild_id, ix.user.id)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


# ── /job-admin ────────────────────────────────────────────────────────────────

def _build_job_admin(gid: int, sel_job: str = None):
    """Return (embed, JobAdminView)."""
    db = load_jobs(gid)
    jobs = db.get("jobs", {})

    embed = discord.Embed(title=t(gid, "job_admin_title"), color=EMBED_COLOR)
    if not jobs:
        embed.description = t(gid, "no_jobs")
    else:
        for jid, j in list(jobs.items())[:10]:
            emp_count = len(j.get("employees", {}))
            app_count = sum(1 for a in j.get("applicants", {}).values()
                            if a.get("status") == "pending")
            mode_str = j.get("mode", "rp")
            embed.add_field(
                name=f"{'✅' if j.get('active') else '❌'} {j['name']}",
                value=(
                    f"Mode: **{mode_str}** | Owner: **{j.get('owner_name', '?')}**\n"
                    f"Employees: {emp_count} | Pending: {app_count}"
                ),
                inline=True,
            )

    if sel_job and sel_job in jobs:
        j = jobs[sel_job]
        mode_str = j.get("mode", "rp")
        reward = j.get("rp_reward" if mode_str == "rp" else "passive_reward", 0)
        embed.add_field(
            name=f"— Selected: {j['name']} —",
            value=(
                f"Mode: **{mode_str}** | Active: **{j.get('active', False)}**\n"
                f"Owner: **{j.get('owner_name', '?')}**\n"
                f"Employees: {len(j.get('employees', {}))} | "
                f"Pending: {sum(1 for a in j.get('applicants', {}).values() if a.get('status') == 'pending')}\n"
                f"Reward: **{reward}**"
            ),
            inline=False,
        )

    view = JobAdminView(gid=gid, jobs=jobs, sel_job=sel_job)
    return embed, view


class JobAdminView(discord.ui.View):
    def __init__(self, gid: int, jobs: dict, sel_job: str = None):
        super().__init__(timeout=300)
        self.gid = gid
        self.sel_job = sel_job

        # Row 0: select job
        opts = (
            [discord.SelectOption(
                label=f"{'✅' if j.get('active') else '❌'} {j['name'][:90]}",
                value=jid,
                default=(jid == sel_job))
             for jid, j in list(jobs.items())[:25]]
            or [discord.SelectOption(label="No jobs", value="__none__")]
        )
        sel = discord.ui.Select(
            placeholder="Select job to manage",
            options=opts,
            custom_id="ja_sel",
            row=0,
        )
        sel.callback = self._sel
        self.add_item(sel)

        # Row 1: Create / Done
        create_btn = discord.ui.Button(
            label=t(gid, "create_job_btn"),
            style=discord.ButtonStyle.green,
            custom_id="ja_create",
            row=1,
        )
        done_btn = discord.ui.Button(
            label=t(gid, "done_btn"),
            style=discord.ButtonStyle.danger,
            custom_id="ja_done",
            row=1,
        )
        create_btn.callback = self._create
        done_btn.callback = self._done
        self.add_item(create_btn)
        self.add_item(done_btn)

        if sel_job and sel_job in jobs:
            j = jobs[sel_job]

            # Row 2: Edit / Toggle active / Fire
            edit_btn = discord.ui.Button(
                label="Edit Job",
                style=discord.ButtonStyle.primary,
                custom_id="ja_edit",
                row=2,
            )
            toggle_btn = discord.ui.Button(
                label="Deactivate" if j.get("active") else "Activate",
                style=discord.ButtonStyle.secondary,
                custom_id="ja_toggle",
                row=2,
            )
            rp_ch_btn = discord.ui.Button(
                label="Set RP Channel",
                style=discord.ButtonStyle.secondary,
                custom_id="ja_rpch",
                row=2,
            )
            edit_btn.callback = self._edit
            toggle_btn.callback = self._toggle
            rp_ch_btn.callback = self._set_rp_channel
            self.add_item(edit_btn)
            self.add_item(toggle_btn)
            self.add_item(rp_ch_btn)

            # Row 3: Fire employee / Delete
            fire_btn = discord.ui.Button(
                label=t(gid, "fire_employee_btn"),
                style=discord.ButtonStyle.danger,
                custom_id="ja_fire",
                row=3,
            )
            del_btn = discord.ui.Button(
                label="Delete Job",
                style=discord.ButtonStyle.danger,
                custom_id="ja_del",
                row=3,
            )
            fire_btn.callback = self._fire
            del_btn.callback = self._delete
            self.add_item(fire_btn)
            self.add_item(del_btn)

    async def _sel(self, ix: discord.Interaction):
        v = ix.data["values"][0]
        sel_job = v if v != "__none__" else None
        embed, view = _build_job_admin(self.gid, sel_job)
        await ix.response.edit_message(embed=embed, view=view)

    async def _create(self, ix: discord.Interaction):
        await ix.response.send_modal(CreateJobModal(self.gid))

    async def _edit(self, ix: discord.Interaction):
        db = load_jobs(self.gid)
        j = db["jobs"].get(self.sel_job, {})
        await ix.response.send_modal(EditJobModal(self.gid, self.sel_job, j))

    async def _toggle(self, ix: discord.Interaction):
        db = load_jobs(self.gid)
        j = db["jobs"].get(self.sel_job, {})
        j["active"] = not j.get("active", True)
        save_jobs(self.gid, db)
        embed, view = _build_job_admin(self.gid, self.sel_job)
        await ix.response.edit_message(embed=embed, view=view)

    async def _set_rp_channel(self, ix: discord.Interaction):
        embed, view = _build_rp_channel_view(self.gid, self.sel_job)
        await ix.response.edit_message(embed=embed, view=view)

    async def _fire(self, ix: discord.Interaction):
        embed, view = _build_fire_employee_view(self.gid, self.sel_job)
        await ix.response.edit_message(embed=embed, view=view)

    async def _delete(self, ix: discord.Interaction):
        db = load_jobs(self.gid)
        db["jobs"].pop(self.sel_job, None)
        save_jobs(self.gid, db)
        embed, view = _build_job_admin(self.gid, sel_job=None)
        await ix.response.edit_message(embed=embed, view=view)

    async def _done(self, ix: discord.Interaction):
        embed = discord.Embed(
            description=f"*{t(self.gid, 'panel_closed')}*", color=EMBED_COLOR)
        await ix.response.edit_message(embed=embed, view=None)


# ── RP Channel picker ─────────────────────────────────────────────────────────

def _build_rp_channel_view(gid: int, jid: str):
    db = load_jobs(gid)
    j = db.get("jobs", {}).get(jid, {})
    cur = j.get("rp_channel_id")
    embed = discord.Embed(
        title="Set RP Earning Channel",
        description=f"Current: {f'<#{cur}>' if cur else '*not set*'}",
        color=EMBED_COLOR,
    )
    view = RPChannelView(gid=gid, jid=jid)
    return embed, view


class RPChannelView(discord.ui.View):
    def __init__(self, gid: int, jid: str):
        super().__init__(timeout=300)
        self.gid = gid
        self.jid = jid

        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="rpc_bk",
            row=0,
        )
        bk.callback = self._back
        self.add_item(bk)

        ch_sel = discord.ui.ChannelSelect(
            placeholder="Select RP earning channel",
            channel_types=[discord.ChannelType.text],
            custom_id="rpc_ch",
            row=1,
        )
        ch_sel.callback = self._pick
        self.add_item(ch_sel)

    async def _pick(self, ix: discord.Interaction):
        db = load_jobs(self.gid)
        job = db["jobs"].get(self.jid, {})
        job["rp_channel_id"] = str(ix.data["values"][0])
        save_jobs(self.gid, db)
        embed, view = _build_job_admin(self.gid, self.jid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _back(self, ix: discord.Interaction):
        embed, view = _build_job_admin(self.gid, self.jid)
        await ix.response.edit_message(embed=embed, view=view)


# ── Fire Employee view ────────────────────────────────────────────────────────

def _build_fire_employee_view(gid: int, jid: str):
    db = load_jobs(gid)
    job = db.get("jobs", {}).get(jid, {})
    emps = job.get("employees", {})
    embed = discord.Embed(
        title=f"Fire Employee — {job.get('name', jid)}",
        description=f"Employees: {len(emps)}",
        color=EMBED_COLOR,
    )
    if emps:
        embed.add_field(
            name="Current Employees",
            value="\n".join(f"• <@{u}>" for u in list(emps.keys())[:15]),
            inline=False,
        )
    view = FireEmployeeView(gid=gid, jid=jid, emps=emps)
    return embed, view


class FireEmployeeView(discord.ui.View):
    def __init__(self, gid: int, jid: str, emps: dict):
        super().__init__(timeout=300)
        self.gid = gid
        self.jid = jid

        bk = discord.ui.Button(
            label=t(gid, "back_btn"),
            style=discord.ButtonStyle.secondary,
            custom_id="fe_bk",
            row=0,
        )
        bk.callback = self._back
        self.add_item(bk)

        if emps:
            opts = [
                discord.SelectOption(
                    label=str(u)[:100],
                    value=u,
                    description=f"Hired {time.strftime('%m/%d', time.localtime(e.get('hired_at', 0)))}",
                )
                for u, e in list(emps.items())[:25]
            ]
            sel = discord.ui.Select(
                placeholder="Select employee to fire",
                options=opts,
                custom_id="fe_sel",
                row=1,
            )
            sel.callback = self._fire
            self.add_item(sel)
        else:
            no_btn = discord.ui.Button(
                label=t(gid, "no_applicants"),
                style=discord.ButtonStyle.secondary,
                custom_id="fe_none",
                disabled=True,
                row=1,
            )
            self.add_item(no_btn)

    async def _fire(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        db = load_jobs(self.gid)
        job = db["jobs"].get(self.jid, {})
        job.get("employees", {}).pop(uid, None)
        save_jobs(self.gid, db)
        if ix.guild:
            member = ix.guild.get_member(int(uid))
            if member:
                try:
                    dm = await member.create_dm()
                    fire_embed = discord.Embed(
                        description=t(self.gid, "job_fired", job=job["name"]),
                        color=EMBED_COLOR,
                    )
                    await dm.send(embed=fire_embed)
                except Exception:
                    pass
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} fired <@{uid}> from '{job['name']}'")
        embed, view = _build_job_admin(self.gid, self.jid)
        await ix.response.edit_message(embed=embed, view=view)

    async def _back(self, ix: discord.Interaction):
        embed, view = _build_job_admin(self.gid, self.jid)
        await ix.response.edit_message(embed=embed, view=view)


# ── Create Job Modal ──────────────────────────────────────────────────────────

class CreateJobModal(Modal, title="Create Job"):
    f_name = TextInput(label="Job Name", max_length=60)
    f_owner = TextInput(label="Owner Name", max_length=60)
    f_desc = TextInput(label="Description", style=discord.TextStyle.paragraph,
                       max_length=300, required=False)
    f_owner_id = TextInput(
        label="Owner Discord User ID (optional)", max_length=20, required=False)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid
        self.f_name.label = t(gid, "job_name_field")
        self.f_owner.label = t(gid, "job_owner_field")
        self.f_desc.label = t(gid, "job_desc_field")

    async def on_submit(self, ix: discord.Interaction):
        jid = str(uuid.uuid4())[:8]
        db = load_jobs(self.gid)
        db["jobs"][jid] = {
            "id": jid,
            "name": self.f_name.value.strip(),
            "description": (self.f_desc.value or "").strip(),
            "owner_name": self.f_owner.value.strip(),
            "owner_id": (self.f_owner_id.value or "").strip() or None,
            "mode": "rp",
            "rp_channel_id": None,
            "rp_min_letters": 50,
            "rp_cooldown_seconds": 3600,
            "rp_reward": 100,
            "passive_reward": 30,
            "passive_interval_seconds": 3600,
            "applicants": {},
            "employees": {},
            "active": True,
        }
        save_jobs(self.gid, db)
        await log_event(bot, self.gid, "job",
                        f"{ix.user.display_name} created job '{self.f_name.value.strip()}'")
        embed, view = _build_job_admin(self.gid, sel_job=jid)
        await ix.response.edit_message(embed=embed, view=view)
        await ix.followup.send(
            t(self.gid, "job_created", name=self.f_name.value.strip()), ephemeral=True)


# ── Edit Job Modal ────────────────────────────────────────────────────────────

class EditJobModal(Modal, title="Edit Job"):
    f_mode = TextInput(label="Mode (rp / passive)", max_length=10)
    f_min_let = TextInput(label="Min letters (RP mode)", max_length=5)
    f_cooldown = TextInput(label="RP cooldown (seconds)", max_length=8)
    f_reward = TextInput(label="RP reward per round", max_length=8)
    f_p_interval = TextInput(label="Passive interval (seconds)", max_length=8)

    def __init__(self, gid: int, jid: str, job: dict):
        super().__init__()
        self.gid = gid
        self.jid = jid
        self.f_mode.default = job.get("mode", "rp")
        self.f_min_let.default = str(job.get("rp_min_letters", 50))
        self.f_cooldown.default = str(job.get("rp_cooldown_seconds", 3600))
        self.f_reward.default = str(job.get("rp_reward", 100))
        self.f_p_interval.default = str(job.get("passive_interval_seconds", 3600))

    async def on_submit(self, ix: discord.Interaction):
        db = load_jobs(self.gid)
        job = db["jobs"].get(self.jid, {})
        mode = self.f_mode.value.strip().lower()
        if mode not in ("rp", "passive"):
            mode = "rp"

        def _int(v, d):
            try:
                return max(0, int(v.strip()))
            except Exception:
                return d

        job["mode"] = mode
        job["rp_min_letters"] = _int(self.f_min_let.value, 50)
        job["rp_cooldown_seconds"] = _int(self.f_cooldown.value, 3600)
        job["rp_reward"] = _int(self.f_reward.value, 100)
        job["passive_interval_seconds"] = _int(self.f_p_interval.value, 3600)
        save_jobs(self.gid, db)
        embed, view = _build_job_admin(self.gid, self.jid)
        await ix.response.edit_message(embed=embed, view=view)


# ── /job-admin slash command ──────────────────────────────────────────────────

@bot.tree.command(
    name="job-admin",
    description="Admin job management panel",
    description_localizations={"th": "แผงจัดการงานสำหรับแอดมิน"},
)
async def job_admin_cmd(ix: discord.Interaction):
    if not ix.guild:
        return
    m = ix.guild.get_member(ix.user.id)
    if not m or not _member_is_admin(m):
        embed = discord.Embed(
            description=t(ix.guild_id, "admin_only"), color=EMBED_COLOR)
        await ix.response.send_message(embed=embed, ephemeral=True)
        return
    embed, view = _build_job_admin(ix.guild_id, sel_job=None)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)
