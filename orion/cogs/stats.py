"""Orion — stats training system with E-→EX progression and per-attribute ranks."""
import random
import time
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR, RANKS, ATTRIBUTES, ATTR_LABELS,
    XP_PER_RANK, DEFAULT_CAP, rank_index, next_rank, progress_bar,
    default_stats, overall_rank, format_cooldown,
    load_players, save_players, load_config, save_config,
    cooldown_remaining, set_cooldown, money_str, add_money, get_wallet,
    run_minigame, MINIGAME_KEYS,
)

TRAIN_COOLDOWN_KEY = "train"
WIN_XP_RANGE = (20, 35)


def _rank_cap(gid: int, uid: int) -> str:
    """Return the effective rank cap for this user."""
    cfg = load_config(gid)
    cap = cfg.get("rank_cap", DEFAULT_CAP)
    # Check exceed-cap roles
    exceed_role_ids = cfg.get("exceed_cap_roles", [])
    if exceed_role_ids:
        import discord as _d
        # We can't check guild member here without guild context, caller must do it
        pass
    return cap


def _user_exceeds_cap(member: discord.Member, cfg: dict) -> bool:
    exceed_role_ids = cfg.get("exceed_cap_roles", [])
    if not exceed_role_ids:
        return False
    member_role_ids = {r.id for r in member.roles}
    return bool(member_role_ids & {int(r) for r in exceed_role_ids})


# ── /training-stats command ───────────────────────────────────────────────────

@bot.tree.command(
    name="training",
    description="ฝึกฝนสถิติตัวละคร — เลือก Attribute และเล่น Minigame",
)
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_training(ix: discord.Interaction):
    gid     = ix.guild_id
    uid     = ix.user.id
    players = load_players(gid)
    player  = players.get(str(uid))

    if not player or player.get("status") != "active":
        await ix.response.send_message(
            embed=discord.Embed(
                description="คุณยังไม่มีตัวละคร ใช้ `/orion` เพื่อสร้าง",
                color=discord.Color.red(),
            ),
            ephemeral=True,
        )
        return

    # Check cooldown
    remaining = cooldown_remaining(gid, uid, TRAIN_COOLDOWN_KEY)
    if remaining > 0:
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"⏳ คูลดาวน์การฝึก: **{format_cooldown(remaining)}**",
                color=0xF59E0B,
            ),
            ephemeral=True,
        )
        return

    cfg  = load_config(gid)
    cost = cfg.get("train_cost", 50)
    bal  = get_wallet(gid, uid)

    embed = discord.Embed(
        title="🏋️ ฝึกฝน",
        description=(
            f"ค่าฝึก: **{money_str(cost, gid)}**\n"
            f"เงินของคุณ: **{money_str(bal, gid)}**\n\n"
            "เลือก Attribute ที่ต้องการพัฒนา:"
        ),
        color=EMBED_COLOR,
    )
    view = TrainingAttrView(uid, gid, cost)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class TrainingAttrView(discord.ui.View):
    def __init__(self, uid: int, gid: int, cost: int):
        super().__init__(timeout=60)
        self.uid  = uid
        self.gid  = gid
        self.cost = cost
        cfg       = load_config(gid)
        self.cap  = cfg.get("rank_cap", DEFAULT_CAP)
        self._build()

    def _build(self):
        self.clear_items()
        players = load_players(self.gid)
        stats   = players.get(str(self.uid), {}).get("stats", default_stats())

        for attr in ATTRIBUTES:
            s    = stats.get(attr, {"rank": "E-", "xp": 0})
            rank = s.get("rank", "E-")
            xp   = s.get("xp", 0)
            bar  = progress_bar(xp)
            btn  = discord.ui.Button(
                label=f"{ATTR_LABELS[attr]} [{rank}] {bar}",
                style=discord.ButtonStyle.secondary,
                row=ATTRIBUTES.index(attr) // 2,
            )
            btn.callback = self._make_train_cb(attr)
            self.add_item(btn)

        cancel = discord.ui.Button(
            label="ยกเลิก", style=discord.ButtonStyle.danger, row=2
        )
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_train_cb(self, attr: str):
        async def _cb(ix: discord.Interaction):
            if ix.user.id != self.uid:
                await ix.response.send_message("นี่ไม่ใช่เซสชันของคุณ", ephemeral=True)
                return

            gid = self.gid
            uid = self.uid
            cfg = load_config(gid)

            # Deduct cost
            bal = get_wallet(gid, uid)
            if bal < self.cost:
                await ix.response.send_message(
                    embed=discord.Embed(
                        description=f"❌ เงินไม่พอ (ต้องการ {money_str(self.cost, gid)})",
                        color=discord.Color.red(),
                    ),
                    ephemeral=True,
                )
                return
            add_money(gid, uid, -self.cost)

            # Check cap
            players = load_players(gid)
            player  = players.get(str(uid), {})
            stats   = player.get("stats", default_stats())
            current = stats.get(attr, {"rank": "E-", "xp": 0})
            rank    = current.get("rank", "E-")

            cap_exceeded = (
                rank_index(rank) >= rank_index(self.cap)
                and not _user_exceeds_cap(ix.user, cfg)
            )

            if cap_exceeded:
                add_money(gid, uid, self.cost)  # refund
                await ix.response.send_message(
                    embed=discord.Embed(
                        description=f"⚠️ {ATTR_LABELS[attr]} ถึง Cap แล้ว ({self.cap})",
                        color=0xF59E0B,
                    ),
                    ephemeral=True,
                )
                return

            # Disable buttons during minigame
            self.clear_items()
            await ix.response.edit_message(
                embed=discord.Embed(
                    title="🎮 เริ่มมินิเกม!",
                    description=f"กำลังฝึก **{ATTR_LABELS[attr]}**\nตอบให้ถูกต้องเพื่อรับ XP!",
                    color=EMBED_COLOR,
                ),
                view=self,
            )

            # Run minigame — send new ephemeral message
            mg_keys = cfg.get("training_minigames", MINIGAME_KEYS)
            key     = random.choice(mg_keys) if mg_keys else None
            won     = await run_minigame(ix, key)

            # Apply result
            players = load_players(gid)
            player  = players.get(str(uid), {})
            stats   = player.setdefault("stats", default_stats())
            attr_s  = stats.setdefault(attr, {"rank": "E-", "xp": 0})

            cd_secs = cfg.get("train_cooldown", 3600)

            if won:
                xp_gain = random.randint(*WIN_XP_RANGE)
                attr_s["xp"] = attr_s.get("xp", 0) + xp_gain
                # Advance rank if XP full
                rank_up_msg = ""
                while attr_s["xp"] >= XP_PER_RANK:
                    nr = next_rank(attr_s["rank"])
                    cap_hit = (
                        not _user_exceeds_cap(ix.user, cfg)
                        and rank_index(attr_s["rank"]) >= rank_index(self.cap)
                    )
                    if nr is None or cap_hit:
                        attr_s["xp"] = XP_PER_RANK  # cap at full
                        break
                    attr_s["xp"]  -= XP_PER_RANK
                    attr_s["rank"] = nr
                    rank_up_msg    = f"\n🎉 **{ATTR_LABELS[attr]} เพิ่มขึ้นเป็น {nr}!**"

                result_text = f"✅ ฝึกสำเร็จ! +{xp_gain} XP{rank_up_msg}"
                result_color = discord.Color.green()
            else:
                result_text  = "❌ ฝึกไม่สำเร็จ คูลดาวน์เริ่มต้น"
                result_color = discord.Color.red()

            players[str(uid)] = player
            save_players(gid, players)
            set_cooldown(gid, uid, TRAIN_COOLDOWN_KEY, cd_secs)

            result_embed = discord.Embed(
                title="🏋️ ผลการฝึก",
                description=(
                    result_text + "\n\n"
                    f"**{ATTR_LABELS[attr]}**: [{attr_s['rank']}] "
                    f"`{progress_bar(attr_s['xp'])}` {attr_s['xp']}/{XP_PER_RANK} XP\n"
                    f"⏳ คูลดาวน์: {format_cooldown(cd_secs)}"
                ),
                color=result_color,
            )
            # The minigame already responded via a new ephemeral message,
            # so we update the original menu message
            try:
                await ix.edit_original_response(embed=result_embed, view=None)
            except Exception:
                pass

        return _cb

    async def _cancel(self, ix: discord.Interaction):
        await ix.response.edit_message(
            embed=discord.Embed(description="ยกเลิกการฝึก", color=EMBED_COLOR),
            view=None,
        )


# ── /training-config (admin) ──────────────────────────────────────────────────

@bot.tree.command(
    name="training-config",
    description="[Admin] ตั้งค่าระบบ Training",
)
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_training_config(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    gid  = ix.guild_id
    cfg  = load_config(gid)
    view = TrainingConfigView(gid)
    embed = _training_config_embed(gid, cfg)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


def _training_config_embed(gid: int, cfg: dict) -> discord.Embed:
    cap        = cfg.get("rank_cap", DEFAULT_CAP)
    cost       = cfg.get("train_cost", 50)
    cd         = cfg.get("train_cooldown", 3600)
    exceed_ids = cfg.get("exceed_cap_roles", [])
    embed = discord.Embed(title="⚙️ Training Config", color=EMBED_COLOR)
    embed.add_field(name="Rank Cap (ขีดจำกัด)", value=cap, inline=True)
    embed.add_field(name="ค่าฝึก", value=money_str(cost, gid), inline=True)
    embed.add_field(name="คูลดาวน์", value=format_cooldown(cd), inline=True)
    exceed_str = ", ".join(f"<@&{r}>" for r in exceed_ids) or "—"
    embed.add_field(name="Roles ที่เกิน Cap ได้", value=exceed_str, inline=False)
    return embed


class TrainingConfigView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    @discord.ui.button(label="🔢 ตั้ง Cap", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cap(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(SetCapModal(self.gid))

    @discord.ui.button(label="💰 ตั้งค่าฝึก", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cost(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(SetTrainCostModal(self.gid))

    @discord.ui.button(label="⏱️ ตั้งคูลดาวน์", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cd(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(SetTrainCooldownModal(self.gid))

    @discord.ui.button(label="🌟 Exceed-Cap Role", style=discord.ButtonStyle.primary, row=1)
    async def btn_exceed(self, ix: discord.Interaction, _: discord.ui.Button):
        view = ExceedCapRoleView(self.gid, self)
        embed = discord.Embed(
            description="เลือก Role ที่สามารถเกิน Cap ได้:",
            color=EMBED_COLOR,
        )
        await ix.response.edit_message(embed=embed, view=view)

    async def _refresh(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        await ix.response.edit_message(
            embed=_training_config_embed(self.gid, cfg), view=self
        )


class SetCapModal(discord.ui.Modal, title="ตั้ง Rank Cap"):
    cap = discord.ui.TextInput(
        label=f"Cap (เช่น B+, A-, S, EX)",
        max_length=4,
    )

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        val = self.cap.value.strip().upper()
        if val not in RANKS:
            await ix.response.send_message(f"Rank ไม่ถูกต้อง: `{val}`", ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg["rank_cap"] = val
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(description=f"✅ Rank Cap → **{val}**", color=EMBED_COLOR),
            ephemeral=True,
        )


class SetTrainCostModal(discord.ui.Modal, title="ตั้งค่าฝึก"):
    cost = discord.ui.TextInput(label="ค่าฝึก (จำนวน)", max_length=10)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        try:
            val = max(0, int(self.cost.value.strip()))
        except ValueError:
            await ix.response.send_message("ตัวเลขไม่ถูกต้อง", ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg["train_cost"] = val
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ ค่าฝึก → {money_str(val, self.gid)}",
                color=EMBED_COLOR,
            ),
            ephemeral=True,
        )


class SetTrainCooldownModal(discord.ui.Modal, title="ตั้งคูลดาวน์"):
    secs = discord.ui.TextInput(label="คูลดาวน์ (วินาที)", max_length=8)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        try:
            val = max(0, int(self.secs.value.strip()))
        except ValueError:
            await ix.response.send_message("ตัวเลขไม่ถูกต้อง", ephemeral=True)
            return
        cfg = load_config(self.gid)
        cfg["train_cooldown"] = val
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ คูลดาวน์ → {format_cooldown(val)}",
                color=EMBED_COLOR,
            ),
            ephemeral=True,
        )


class ExceedCapRoleView(discord.ui.View):
    def __init__(self, gid: int, parent: TrainingConfigView):
        super().__init__(timeout=120)
        self.gid    = gid
        self.parent = parent
        sel = discord.ui.RoleSelect(
            placeholder="เลือก Role…",
            min_values=0,
            max_values=5,
            row=0,
        )
        sel.callback = self._on_select
        self.add_item(sel)

        back = discord.ui.Button(label="◀ กลับ", style=discord.ButtonStyle.secondary, row=1)
        back.callback = self._back
        self.add_item(back)

    async def _on_select(self, ix: discord.Interaction):
        role_ids = [str(r) for r in ix.data["values"]]
        cfg = load_config(self.gid)
        cfg["exceed_cap_roles"] = role_ids
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(description="✅ บันทึก Exceed-Cap roles แล้ว", color=EMBED_COLOR),
            ephemeral=True,
        )

    async def _back(self, ix: discord.Interaction):
        cfg = load_config(self.gid)
        await ix.response.edit_message(
            embed=_training_config_embed(self.gid, cfg), view=self.parent
        )
