# ============================================================
# ORION — Job System (ระบบงาน)
# ============================================================
# mode "rp"      → ผู้เล่นส่งข้อความใน rp_channel ยาวพอ → รับเงิน + ไอเทม (cooldown)
# mode "passive" → ทุก interval รับเงิน + ไอเทมอัตโนมัติ
#
# Commands:
#   /งาน          — ดูงานที่เปิดรับ, สมัคร, ลาออก
#   /งาน-เจ้าของ  — เจ้าของพิจารณาผู้สมัคร
#   /งาน-แอดมิน  — Admin CRUD + ตั้งรางวัลไอเทม + ไล่ออก
# ============================================================

import sys
import time
import uuid
import discord
from discord.ext import tasks

# ── pull references from orion_bot ──────────────────────────
_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("orion_job ต้องถูก import จาก orion_bot.py เท่านั้น")

bot                       = _orion_bot_mod.bot
ORION_GUILD_ID            = _orion_bot_mod.ORION_GUILD_ID
ALLOWED_COMMAND_GUILD_IDS = _orion_bot_mod.ALLOWED_COMMAND_GUILD_IDS
_ORION_GUILD_OBJ          = _orion_bot_mod._ORION_GUILD_OBJ
ORION_DATA_DIR            = _orion_bot_mod.ORION_DATA_DIR
load_json                 = _orion_bot_mod.load_json
save_json                 = _orion_bot_mod.save_json
ensure_orion_player       = _orion_bot_mod.ensure_orion_player
add_money                 = _orion_bot_mod.add_money
money_str                 = _orion_bot_mod.money_str
load_orion_players        = _orion_bot_mod.load_orion_players

import orion_items
add_player_item    = orion_items.add_player_item
load_items_catalog = orion_items.load_items_catalog

# ── constants ────────────────────────────────────────────────
JOBS_FILE = f"{ORION_DATA_DIR}/jobs.json"
_PER_PAGE = 6

# ── data helpers ─────────────────────────────────────────────
def load_jobs() -> dict:
    d = load_json(JOBS_FILE, {})
    d.setdefault("jobs", {})
    return d

def save_jobs(d: dict):
    save_json(JOBS_FILE, d)

def _is_admin(member: discord.Member) -> bool:
    return (member.guild_permissions.administrator or
            member.guild_permissions.manage_guild)


# ── reward helper ────────────────────────────────────────────
async def _give_rewards(uid: str, member: discord.Member, job: dict, mode: str):
    money_key = "rp_reward_money"      if mode == "rp" else "passive_reward_money"
    items_key = "rp_reward_items"      if mode == "rp" else "passive_reward_items"
    money     = job.get(money_key, 0)
    items     = job.get(items_key, [])

    lines = []
    if money > 0:
        add_money(uid, money)
        lines.append(f"💰 {money_str(money)}")
    catalog = load_items_catalog()
    for r in items:
        iid = r.get("item_id", "")
        qty = max(1, int(r.get("qty", 1)))
        if not iid:
            continue
        add_player_item(uid, iid, qty)
        item  = catalog.get(iid, {})
        emoji = item.get("emoji", "📦")
        name  = item.get("name", iid)
        lines.append(f"{emoji} {name} ×{qty}")

    if not lines:
        return
    try:
        await member.send(embed=discord.Embed(
            title=f"💼 {job['name']} — รับรางวัล",
            description="\n".join(lines),
            color=discord.Color.gold(),
        ))
    except Exception:
        pass


# ── background: passive income ───────────────────────────────
@tasks.loop(minutes=1)
async def _orion_passive_income():
    now = time.time()
    for guild in bot.guilds:
        if guild.id not in ALLOWED_COMMAND_GUILD_IDS:
            continue
        db      = load_jobs()
        changed = False
        for job in db.get("jobs", {}).values():
            if not job.get("active") or job.get("mode") != "passive":
                continue
            interval = job.get("passive_interval_seconds", 3600)
            if interval <= 0:
                continue
            for uid, emp in list(job.get("employees", {}).items()):
                if now - emp.get("last_passive_earned", 0) < interval:
                    continue
                member = guild.get_member(int(uid))
                if not member:
                    continue
                emp["last_passive_earned"] = now
                changed = True
                await _give_rewards(uid, member, job, "passive")
        if changed:
            save_jobs(db)


def start_job_tasks():
    if not _orion_passive_income.is_running():
        _orion_passive_income.start()


# ── on_message: RP earning ───────────────────────────────────
@bot.listen("on_message")
async def _orion_job_on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    if message.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        return
    db      = load_jobs()
    uid     = str(message.author.id)
    now     = time.time()
    changed = False

    for job in db.get("jobs", {}).values():
        if not job.get("active") or job.get("mode") != "rp":
            continue
        if uid not in job.get("employees", {}):
            continue
        rp_ch = job.get("rp_channel_id")
        if not rp_ch or str(message.channel.id) != str(rp_ch):
            continue
        if len(message.content) < job.get("rp_min_letters", 50):
            continue
        emp = job["employees"][uid]
        if now - emp.get("last_rp_earned", 0) < job.get("rp_cooldown_seconds", 3600):
            continue
        emp["last_rp_earned"] = now
        changed = True
        await _give_rewards(uid, message.author, job, "rp")

    if changed:
        save_jobs(db)


# ── embed helpers ────────────────────────────────────────────
def _reward_str(job: dict, mode: str) -> str:
    money_key = "rp_reward_money" if mode == "rp" else "passive_reward_money"
    items_key = "rp_reward_items" if mode == "rp" else "passive_reward_items"
    money   = job.get(money_key, 0)
    items   = job.get(items_key, [])
    catalog = load_items_catalog()
    parts   = []
    if money:
        parts.append(money_str(money))
    for r in items:
        item  = catalog.get(r.get("item_id", ""), {})
        emoji = item.get("emoji", "📦")
        name  = item.get("name", r.get("item_id", "?"))
        parts.append(f"{emoji} {name} ×{r.get('qty', 1)}")
    return ", ".join(parts) if parts else "—"


def _job_embed(job: dict, jid: str = "") -> discord.Embed:
    mode     = job.get("mode", "rp")
    mode_str = "📝 RP" if mode == "rp" else "💤 Passive"
    embed    = discord.Embed(
        title=f"💼 {job['name']}",
        description=job.get("description") or "",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Mode",     value=mode_str,                              inline=True)
    embed.add_field(name="สถานะ",   value="✅ เปิดรับ" if job.get("active") else "❌ ปิด", inline=True)
    embed.add_field(name="เจ้าของ", value=job.get("owner_name", "?"),             inline=True)
    embed.add_field(name="รางวัลต่อรอบ", value=_reward_str(job, mode),           inline=False)
    emp_c  = len(job.get("employees", {}))
    pend_c = sum(1 for a in job.get("applicants", {}).values() if a.get("status") == "pending")
    embed.add_field(name="พนักงาน",     value=str(emp_c),  inline=True)
    embed.add_field(name="รอพิจารณา",  value=str(pend_c), inline=True)
    if mode == "rp":
        embed.add_field(
            name="RP cooldown",
            value=f"{job.get('rp_cooldown_seconds', 3600) // 60} นาที  |  อักขระขั้นต่ำ {job.get('rp_min_letters', 50)}",
            inline=False,
        )
    else:
        secs = job.get("passive_interval_seconds", 3600)
        embed.add_field(name="Passive interval", value=f"{secs // 60} นาที", inline=False)
    if jid:
        embed.set_footer(text=f"ID: {jid}")
    return embed


# ── /งาน ─────────────────────────────────────────────────────
class _JobListView(discord.ui.View):
    def __init__(self, uid: int, page: int = 0):
        super().__init__(timeout=300)
        self.uid = uid; self.page = page
        self._build()

    def _build(self):
        self.clear_items()
        db    = load_jobs()
        jobs  = [(jid, j) for jid, j in db.get("jobs", {}).items() if j.get("active")]
        total = max(1, (len(jobs) + _PER_PAGE - 1) // _PER_PAGE)
        self.page = max(0, min(self.page, total - 1))
        chunk = jobs[self.page * _PER_PAGE:(self.page + 1) * _PER_PAGE]

        for row_i, (jid, j) in enumerate(chunk):
            mode_icon = "📝" if j.get("mode") == "rp" else "💤"
            applied   = str(self.uid) in j.get("applicants", {})
            employed  = str(self.uid) in j.get("employees", {})
            suffix    = " ✅" if employed else (" ⏳" if applied else "")
            btn = discord.ui.Button(
                label=f"{mode_icon} {j['name'][:38]}{suffix}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"jl_v_{jid}",
                row=row_i,
            )
            btn.callback = self._make_detail(jid)
            self.add_item(btn)

        prev_btn = discord.ui.Button(label="◀",      style=discord.ButtonStyle.secondary,
                                      custom_id="jl_p", disabled=(self.page == 0), row=4)
        next_btn = discord.ui.Button(label="▶",      style=discord.ButtonStyle.secondary,
                                      custom_id="jl_n", disabled=(self.page >= total - 1), row=4)
        done_btn = discord.ui.Button(label="❌ ปิด", style=discord.ButtonStyle.danger,
                                      custom_id="jl_d", row=4)
        prev_btn.callback = self._prev
        next_btn.callback = self._next
        done_btn.callback = self._done
        self.add_item(prev_btn); self.add_item(next_btn); self.add_item(done_btn)

    def _make_detail(self, jid: str):
        async def _cb(ix: discord.Interaction):
            db  = load_jobs()
            job = db.get("jobs", {}).get(jid)
            if not job:
                await ix.response.send_message("ไม่พบงานนี้แล้ว", ephemeral=True); return
            uid      = str(self.uid)
            applied  = uid in job.get("applicants", {})
            employed = uid in job.get("employees", {})
            await ix.response.send_message(
                embed=_job_embed(job, jid),
                view=_JobDetailView(self.uid, jid, applied, employed),
                ephemeral=True,
            )
        return _cb

    async def _prev(self, ix): self.page -= 1; self._build(); await ix.response.edit_message(view=self)
    async def _next(self, ix): self.page += 1; self._build(); await ix.response.edit_message(view=self)
    async def _done(self, ix): self.clear_items(); await ix.response.edit_message(content="*ปิดแล้ว*", view=self)


class _JobDetailView(discord.ui.View):
    def __init__(self, uid: int, jid: str, applied: bool, employed: bool):
        super().__init__(timeout=300)
        self.uid = uid; self.jid = jid
        apply_btn = discord.ui.Button(
            label="📩 สมัครงาน",
            style=discord.ButtonStyle.green if not applied and not employed else discord.ButtonStyle.secondary,
            custom_id="jd_apply",
            disabled=(applied or employed),
            row=0,
        )
        apply_btn.callback = self._apply
        self.add_item(apply_btn)
        if employed:
            quit_btn = discord.ui.Button(label="🚪 ลาออก", style=discord.ButtonStyle.danger,
                                          custom_id="jd_quit", row=0)
            quit_btn.callback = self._quit
            self.add_item(quit_btn)

    async def _apply(self, ix: discord.Interaction):
        db  = load_jobs()
        job = db.get("jobs", {}).get(self.jid)
        if not job or not job.get("active"):
            await ix.response.send_message("งานนี้ปิดรับแล้ว", ephemeral=True); return
        uid = str(self.uid)
        if uid in job.get("applicants", {}):
            await ix.response.send_message("คุณสมัครงานนี้ไปแล้ว", ephemeral=True); return
        char_name = load_orion_players().get(uid, {}).get("char_name", ix.user.display_name)
        job.setdefault("applicants", {})[uid] = {
            "applied_at": time.time(), "status": "pending",
            "char_name": char_name, "display_name": ix.user.display_name,
        }
        save_jobs(db)
        owner_id = job.get("owner_id")
        if owner_id:
            for g in bot.guilds:
                m = g.get_member(int(owner_id))
                if m:
                    try:
                        await m.send(embed=discord.Embed(
                            description=(f"📩 **{ix.user.display_name}** (`{char_name}`) "
                                         f"สมัคร **{job['name']}**\nใช้ `/งาน-เจ้าของ` เพื่อพิจารณา"),
                            color=discord.Color.blue(),
                        ))
                    except Exception:
                        pass
                    break
        self.children[0].disabled = True
        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"✅ ส่งใบสมัคร **{job['name']}** แล้ว รอเจ้าของพิจารณา",
                color=discord.Color.green(),
            ),
            view=self,
        )

    async def _quit(self, ix: discord.Interaction):
        db  = load_jobs()
        job = db.get("jobs", {}).get(self.jid)
        if not job:
            await ix.response.send_message("ไม่พบงาน", ephemeral=True); return
        uid = str(self.uid)
        job.get("employees", {}).pop(uid, None)
        app = job.get("applicants", {}).get(uid)
        if app:
            app["status"] = "left"
        save_jobs(db)
        self.clear_items()
        await ix.response.edit_message(
            embed=discord.Embed(
                description=f"🚪 ลาออกจาก **{job['name']}** แล้ว",
                color=discord.Color.orange(),
            ),
            view=self,
        )


@bot.tree.command(name="งาน", description="ดูงานที่เปิดรับและสมัครงาน", guild=_ORION_GUILD_OBJ)
async def cmd_job(ix: discord.Interaction):
    if not ix.guild or ix.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        return
    ensure_orion_player(str(ix.user.id))
    db   = load_jobs()
    jobs = [j for j in db.get("jobs", {}).values() if j.get("active")]
    if not jobs:
        await ix.response.send_message(
            embed=discord.Embed(description="ยังไม่มีงานที่เปิดรับในขณะนี้ 📭", color=discord.Color.orange()),
            ephemeral=True,
        )
        return
    await ix.response.send_message(view=_JobListView(ix.user.id), ephemeral=True)


# ── /งาน-เจ้าของ ─────────────────────────────────────────────
class _JobOwnerView(discord.ui.View):
    def __init__(self, uid: int):
        super().__init__(timeout=300)
        self.uid = uid; self.sel_job: str | None = None; self.sel_app: str | None = None
        self._build()

    def _build(self):
        self.clear_items()
        db   = load_jobs()
        mine = [(jid, j) for jid, j in db.get("jobs", {}).items()
                if str(j.get("owner_id", "")) == str(self.uid)]
        if not mine:
            done = discord.ui.Button(label="❌ ปิด", style=discord.ButtonStyle.secondary, custom_id="jo_done", row=0)
            done.callback = self._done
            self.add_item(done)
            return

        opts = [discord.SelectOption(label=f"{'✅' if j.get('active') else '❌'} {j['name'][:90]}",
                                      value=jid, default=(jid == self.sel_job))
                for jid, j in mine[:25]]
        sel = discord.ui.Select(placeholder="เลือกงานของคุณ", options=opts, row=0)
        sel.callback = self._sel_job
        self.add_item(sel)

        if self.sel_job:
            job   = db["jobs"].get(self.sel_job, {})
            pend  = [(uid, a) for uid, a in job.get("applicants", {}).items()
                     if a.get("status") == "pending"]
            if pend:
                app_opts = [discord.SelectOption(
                    label=f"{a['display_name']} ({a['char_name']})".ljust(1)[:100],
                    value=uid, default=(uid == self.sel_app))
                    for uid, a in pend[:25]]
                app_sel = discord.ui.Select(placeholder=f"ผู้สมัคร {len(pend)} คน", options=app_opts, row=1)
                app_sel.callback = self._sel_app
                self.add_item(app_sel)
                if self.sel_app:
                    acc = discord.ui.Button(label="✅ รับเข้าทำงาน", style=discord.ButtonStyle.green,
                                             custom_id="jo_acc", row=2)
                    dec = discord.ui.Button(label="❌ ปฏิเสธ",       style=discord.ButtonStyle.danger,
                                             custom_id="jo_dec", row=2)
                    acc.callback = self._accept
                    dec.callback = self._decline
                    self.add_item(acc); self.add_item(dec)

        done = discord.ui.Button(label="❌ ปิด", style=discord.ButtonStyle.secondary, custom_id="jo_done_b", row=4)
        done.callback = self._done
        self.add_item(done)

    async def _sel_job(self, ix):
        self.sel_job = ix.data["values"][0]; self.sel_app = None
        self._build(); await ix.response.edit_message(view=self)

    async def _sel_app(self, ix):
        self.sel_app = ix.data["values"][0]
        self._build(); await ix.response.edit_message(view=self)

    async def _accept(self, ix: discord.Interaction):
        db  = load_jobs()
        job = db["jobs"].get(self.sel_job, {})
        app = job.get("applicants", {}).get(self.sel_app, {})
        app["status"] = "accepted"
        job.setdefault("employees", {})[self.sel_app] = {
            "hired_at": time.time(), "last_rp_earned": 0, "last_passive_earned": 0,
        }
        save_jobs(db)
        for g in bot.guilds:
            m = g.get_member(int(self.sel_app))
            if m:
                try:
                    await m.send(embed=discord.Embed(
                        description=f"🎉 ใบสมัคร **{job['name']}** ได้รับการอนุมัติแล้ว! ยินดีต้อนรับ",
                        color=discord.Color.green()))
                except Exception:
                    pass
                break
        self.sel_app = None; self._build(); await ix.response.edit_message(view=self)

    async def _decline(self, ix: discord.Interaction):
        db  = load_jobs()
        job = db["jobs"].get(self.sel_job, {})
        app = job.get("applicants", {}).get(self.sel_app, {})
        app["status"] = "declined"
        save_jobs(db)
        for g in bot.guilds:
            m = g.get_member(int(self.sel_app))
            if m:
                try:
                    await m.send(embed=discord.Embed(
                        description=f"😔 ใบสมัคร **{job['name']}** ไม่ผ่านการคัดเลือก",
                        color=discord.Color.red()))
                except Exception:
                    pass
                break
        self.sel_app = None; self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix): self.clear_items(); await ix.response.edit_message(content="*ปิดแล้ว*", view=self)


@bot.tree.command(name="งาน-เจ้าของ", description="จัดการผู้สมัครและพนักงานของงานคุณ", guild=_ORION_GUILD_OBJ)
async def cmd_job_owner(ix: discord.Interaction):
    if not ix.guild or ix.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        return
    await ix.response.send_message(view=_JobOwnerView(ix.user.id), ephemeral=True)


# ── /งาน-แอดมิน ──────────────────────────────────────────────
class _JobAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.sel_job: str | None = None
        self._build()

    def _build(self):
        self.clear_items()
        db   = load_jobs()
        jobs = db.get("jobs", {})

        opts = ([discord.SelectOption(
                     label=f"{'✅' if j.get('active') else '❌'} {j['name'][:90]}",
                     value=jid, default=(jid == self.sel_job))
                 for jid, j in list(jobs.items())[:25]]
                or [discord.SelectOption(label="(ยังไม่มีงาน)", value="__none__")])
        sel = discord.ui.Select(placeholder="เลือกงาน", options=opts, row=0)
        sel.callback = self._sel
        self.add_item(sel)

        if self.sel_job and self.sel_job in jobs:
            j = jobs[self.sel_job]
            edit_btn   = discord.ui.Button(label="✏️ แก้ไข",       style=discord.ButtonStyle.primary,   custom_id="ja_edit",   row=1)
            toggle_btn = discord.ui.Button(
                label="🔴 ปิดงาน" if j.get("active") else "🟢 เปิดงาน",
                style=discord.ButtonStyle.secondary, custom_id="ja_tog", row=1)
            items_btn  = discord.ui.Button(label="🎁 รางวัลไอเทม", style=discord.ButtonStyle.secondary,  custom_id="ja_itm",    row=1)
            rp_ch_btn  = discord.ui.Button(label="📌 ตั้งห้อง RP", style=discord.ButtonStyle.secondary,  custom_id="ja_rp",     row=2)
            fire_btn   = discord.ui.Button(label="👋 ไล่ออก",       style=discord.ButtonStyle.danger,     custom_id="ja_fire",   row=2)
            del_btn    = discord.ui.Button(label="🗑️ ลบงาน",       style=discord.ButtonStyle.danger,     custom_id="ja_del",    row=2)
            edit_btn.callback   = self._edit
            toggle_btn.callback = self._toggle
            items_btn.callback  = self._edit_items
            rp_ch_btn.callback  = self._set_rp_ch
            fire_btn.callback   = self._fire
            del_btn.callback    = self._delete
            for b in (edit_btn, toggle_btn, items_btn, rp_ch_btn, fire_btn, del_btn):
                self.add_item(b)

        create_btn = discord.ui.Button(label="➕ สร้างงาน", style=discord.ButtonStyle.green,     custom_id="ja_new",  row=3)
        done_btn   = discord.ui.Button(label="❌ ปิด",      style=discord.ButtonStyle.secondary, custom_id="ja_done", row=3)
        create_btn.callback = self._create
        done_btn.callback   = self._done
        self.add_item(create_btn); self.add_item(done_btn)

    async def _sel(self, ix):
        v = ix.data["values"][0]; self.sel_job = v if v != "__none__" else None
        self._build(); await ix.response.edit_message(view=self)

    async def _create(self, ix): await ix.response.send_modal(_CreateJobModal(self))
    async def _edit(self, ix):
        db = load_jobs(); j = db["jobs"].get(self.sel_job, {})
        await ix.response.send_modal(_EditJobModal(self.sel_job, j, self))

    async def _toggle(self, ix):
        db = load_jobs(); j = db["jobs"].get(self.sel_job, {})
        j["active"] = not j.get("active", True)
        save_jobs(db); self._build(); await ix.response.edit_message(view=self)

    async def _edit_items(self, ix):
        db  = load_jobs(); job = db.get("jobs", {}).get(self.sel_job, {})
        view = _EditRewardItemsView(self.sel_job, self)
        await ix.response.edit_message(embed=view._info_embed(), view=view)

    async def _set_rp_ch(self, ix):
        await ix.response.edit_message(view=_SetRPChannelView(self.sel_job, self))

    async def _fire(self, ix):
        await ix.response.edit_message(view=_FireEmployeeView(self.sel_job, self))

    async def _delete(self, ix):
        db = load_jobs(); db["jobs"].pop(self.sel_job, None)
        save_jobs(db); self.sel_job = None
        self._build(); await ix.response.edit_message(view=self)

    async def _done(self, ix): self.clear_items(); await ix.response.edit_message(content="*ปิดแล้ว*", view=self)


class _FireEmployeeView(discord.ui.View):
    def __init__(self, jid: str, parent: _JobAdminView):
        super().__init__(timeout=300)
        self.jid = jid; self.parent = parent
        db   = load_jobs()
        job  = db.get("jobs", {}).get(jid, {})
        emps = job.get("employees", {})
        opts = ([discord.SelectOption(
                     label=f"User {uid} — รับเข้า {time.strftime('%d/%m/%y', time.localtime(e.get('hired_at', 0)))}",
                     value=uid)
                 for uid, e in list(emps.items())[:25]]
                or [discord.SelectOption(label="(ไม่มีพนักงาน)", value="__none__")])
        sel = discord.ui.Select(placeholder="เลือกพนักงานที่จะไล่ออก", options=opts, row=0)
        sel.callback = self._fire
        bk = discord.ui.Button(label="◀ กลับ", style=discord.ButtonStyle.secondary, custom_id="fe_bk", row=1)
        bk.callback = self._back
        self.add_item(sel); self.add_item(bk)

    async def _fire(self, ix: discord.Interaction):
        uid = ix.data["values"][0]
        if uid == "__none__": await ix.response.defer(); return
        db  = load_jobs(); job = db["jobs"].get(self.jid, {})
        job.get("employees", {}).pop(uid, None)
        save_jobs(db)
        for g in bot.guilds:
            m = g.get_member(int(uid))
            if m:
                try:
                    await m.send(embed=discord.Embed(
                        description=f"📢 คุณถูกไล่ออกจาก **{job['name']}**",
                        color=discord.Color.red()))
                except Exception:
                    pass
                break
        self.parent._build(); await ix.response.edit_message(embed=None, view=self.parent)

    async def _back(self, ix): self.parent._build(); await ix.response.edit_message(view=self.parent)


class _EditRewardItemsView(discord.ui.View):
    """เลือกไอเทมจาก catalog ตั้งเป็นรางวัล RP / Passive"""
    def __init__(self, jid: str, parent: _JobAdminView):
        super().__init__(timeout=300)
        self.jid = jid; self.parent = parent
        self._build()

    def _build(self):
        self.clear_items()
        catalog = load_items_catalog()
        items   = list(catalog.items())[:25]

        if not items:
            info = discord.ui.Button(label="ยังไม่มีไอเทมใน catalog", style=discord.ButtonStyle.secondary,
                                      custom_id="ir_noop", disabled=True, row=0)
            bk   = discord.ui.Button(label="◀ กลับ", style=discord.ButtonStyle.secondary, custom_id="ir_bk", row=1)
            bk.callback = self._back
            self.add_item(info); self.add_item(bk)
            return

        opts = [discord.SelectOption(
                    label=f"{v.get('emoji','📦')} {v.get('name', k)[:80]}",
                    value=k)
                for k, v in items]

        sel_rp = discord.ui.Select(placeholder="➕ เพิ่มไอเทมรางวัล RP",      options=opts, row=0)
        sel_ps = discord.ui.Select(placeholder="➕ เพิ่มไอเทมรางวัล Passive", options=opts, row=1)
        sel_rp.callback = self._add_rp
        sel_ps.callback = self._add_passive

        clr_rp = discord.ui.Button(label="🗑️ ล้าง RP",      style=discord.ButtonStyle.danger,     custom_id="ir_crp", row=2)
        clr_ps = discord.ui.Button(label="🗑️ ล้าง Passive", style=discord.ButtonStyle.danger,     custom_id="ir_cps", row=2)
        bk     = discord.ui.Button(label="◀ กลับ",           style=discord.ButtonStyle.secondary, custom_id="ir_bk",  row=2)
        clr_rp.callback = self._clear_rp
        clr_ps.callback = self._clear_ps
        bk.callback     = self._back
        for w in (sel_rp, sel_ps, clr_rp, clr_ps, bk):
            self.add_item(w)

    def _info_embed(self) -> discord.Embed:
        db      = load_jobs()
        job     = db.get("jobs", {}).get(self.jid, {})
        catalog = load_items_catalog()

        def _fmt(lst: list) -> str:
            if not lst: return "—"
            lines = []
            for r in lst:
                item  = catalog.get(r.get("item_id", ""), {})
                emoji = item.get("emoji", "📦")
                name  = item.get("name", r.get("item_id", "?"))
                lines.append(f"{emoji} **{name}** ×{r.get('qty', 1)}")
            return "\n".join(lines)

        embed = discord.Embed(title=f"🎁 รางวัลไอเทม — {job.get('name', '?')}", color=discord.Color.purple())
        embed.add_field(name="RP reward items",      value=_fmt(job.get("rp_reward_items", [])),      inline=False)
        embed.add_field(name="Passive reward items", value=_fmt(job.get("passive_reward_items", [])), inline=False)
        embed.set_footer(text="qty เริ่มต้นที่ 1 — ใช้ /งาน-แอดมิน → แก้ไข เพื่อปรับค่าอื่น")
        return embed

    async def _add_rp(self, ix: discord.Interaction):
        iid = ix.data["values"][0]
        db  = load_jobs(); job = db["jobs"].get(self.jid, {})
        lst = job.setdefault("rp_reward_items", [])
        if not any(r.get("item_id") == iid for r in lst):
            lst.append({"item_id": iid, "qty": 1})
        save_jobs(db); await ix.response.edit_message(embed=self._info_embed(), view=self)

    async def _add_passive(self, ix: discord.Interaction):
        iid = ix.data["values"][0]
        db  = load_jobs(); job = db["jobs"].get(self.jid, {})
        lst = job.setdefault("passive_reward_items", [])
        if not any(r.get("item_id") == iid for r in lst):
            lst.append({"item_id": iid, "qty": 1})
        save_jobs(db); await ix.response.edit_message(embed=self._info_embed(), view=self)

    async def _clear_rp(self, ix: discord.Interaction):
        db = load_jobs(); db["jobs"][self.jid]["rp_reward_items"] = []
        save_jobs(db); await ix.response.edit_message(embed=self._info_embed(), view=self)

    async def _clear_ps(self, ix: discord.Interaction):
        db = load_jobs(); db["jobs"][self.jid]["passive_reward_items"] = []
        save_jobs(db); await ix.response.edit_message(embed=self._info_embed(), view=self)

    async def _back(self, ix):
        self.parent._build(); await ix.response.edit_message(embed=None, view=self.parent)


class _SetRPChannelView(discord.ui.View):
    def __init__(self, jid: str, parent: _JobAdminView):
        super().__init__(timeout=300)
        self.jid = jid; self.parent = parent
        ch_sel = discord.ui.ChannelSelect(
            placeholder="เลือกห้องสำหรับ RP earning",
            channel_types=[discord.ChannelType.text],
            row=0,
        )
        ch_sel.callback = self._pick
        bk = discord.ui.Button(label="◀ กลับ", style=discord.ButtonStyle.secondary, custom_id="src_bk", row=1)
        bk.callback = self._back
        self.add_item(ch_sel); self.add_item(bk)

    async def _pick(self, ix):
        db  = load_jobs(); job = db["jobs"].get(self.jid, {})
        job["rp_channel_id"] = str(ix.data["values"][0])
        save_jobs(db)
        self.parent._build(); await ix.response.edit_message(view=self.parent)

    async def _back(self, ix): self.parent._build(); await ix.response.edit_message(view=self.parent)


class _CreateJobModal(discord.ui.Modal, title="➕ สร้างงานใหม่"):
    f_name     = discord.ui.TextInput(label="ชื่องาน",                             max_length=60)
    f_owner    = discord.ui.TextInput(label="ชื่อเจ้าของ",                          max_length=60)
    f_desc     = discord.ui.TextInput(label="คำอธิบาย (ไม่บังคับ)",               style=discord.TextStyle.paragraph, max_length=300, required=False)
    f_owner_id = discord.ui.TextInput(label="Discord User ID เจ้าของ (ไม่บังคับ)", max_length=20, required=False)

    def __init__(self, parent: _JobAdminView):
        super().__init__(); self.parent = parent

    async def on_submit(self, ix: discord.Interaction):
        jid = str(uuid.uuid4())[:8]
        db  = load_jobs()
        db["jobs"][jid] = {
            "id":                       jid,
            "name":                     self.f_name.value.strip(),
            "description":              (self.f_desc.value or "").strip(),
            "owner_name":               self.f_owner.value.strip(),
            "owner_id":                 (self.f_owner_id.value or "").strip() or None,
            "mode":                     "rp",
            "rp_channel_id":            None,
            "rp_min_letters":           50,
            "rp_cooldown_seconds":      3600,
            "rp_reward_money":          100,
            "rp_reward_items":          [],
            "passive_reward_money":     30,
            "passive_reward_items":     [],
            "passive_interval_seconds": 3600,
            "applicants":               {},
            "employees":                {},
            "active":                   True,
        }
        save_jobs(db)
        self.parent.sel_job = jid
        self.parent._build()
        await ix.response.edit_message(view=self.parent)
        await ix.followup.send(
            embed=discord.Embed(
                description=f"✅ สร้างงาน **{self.f_name.value.strip()}** แล้ว (ID: `{jid}`)",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )


class _EditJobModal(discord.ui.Modal, title="✏️ แก้ไขงาน"):
    f_mode       = discord.ui.TextInput(label="Mode (rp / passive)",        max_length=10)
    f_rp_money   = discord.ui.TextInput(label="รางวัลเงิน RP ต่อรอบ",       max_length=8)
    f_cooldown   = discord.ui.TextInput(label="RP cooldown (วินาที)",        max_length=8)
    f_pas_money  = discord.ui.TextInput(label="รางวัลเงิน Passive ต่อรอบ",  max_length=8)
    f_p_interval = discord.ui.TextInput(label="Passive interval (วินาที)",   max_length=8)

    def __init__(self, jid: str, job: dict, parent: _JobAdminView):
        super().__init__(); self.jid = jid; self.parent = parent
        self.f_mode.default       = job.get("mode", "rp")
        self.f_rp_money.default   = str(job.get("rp_reward_money", 100))
        self.f_cooldown.default   = str(job.get("rp_cooldown_seconds", 3600))
        self.f_pas_money.default  = str(job.get("passive_reward_money", 30))
        self.f_p_interval.default = str(job.get("passive_interval_seconds", 3600))

    async def on_submit(self, ix: discord.Interaction):
        db  = load_jobs(); job = db["jobs"].get(self.jid, {})
        mode = self.f_mode.value.strip().lower()
        if mode not in ("rp", "passive"): mode = "rp"
        def _i(v, d):
            try: return max(0, int(v.strip()))
            except: return d
        job["mode"]                     = mode
        job["rp_reward_money"]          = _i(self.f_rp_money.value, 100)
        job["rp_cooldown_seconds"]      = _i(self.f_cooldown.value, 3600)
        job["passive_reward_money"]     = _i(self.f_pas_money.value, 30)
        job["passive_interval_seconds"] = _i(self.f_p_interval.value, 3600)
        save_jobs(db)
        self.parent._build(); await ix.response.edit_message(view=self.parent)


@bot.tree.command(name="งาน-แอดมิน", description="[Admin] จัดการระบบงานทั้งหมด", guild=_ORION_GUILD_OBJ)
async def cmd_job_admin(ix: discord.Interaction):
    if not ix.guild or ix.guild.id not in ALLOWED_COMMAND_GUILD_IDS:
        return
    if not _is_admin(ix.user):
        await ix.response.send_message("❌ เฉพาะ Admin เท่านั้น", ephemeral=True); return
    await ix.response.send_message(view=_JobAdminView(), ephemeral=True)


# ── start background task ─────────────────────────────────────
# NOTE: ห้ามเรียก start_job_tasks() ที่ระดับ module — ยังไม่มี event loop
# orion_bot.py จะเรียกใน on_ready ให้แทน
