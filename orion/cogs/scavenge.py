"""Orion — scavenging system with admin-configurable cooldown."""
import random
import discord
from discord import app_commands

from core.instance import bot
from core.shared import (
    GUILD_OBJECTS, EMBED_COLOR,
    load_config, save_config,
    load_json, save_json, get_data_dir,
    load_players, save_players, load_items_catalog,
    cooldown_remaining, set_cooldown, format_cooldown,
    run_minigame, MINIGAME_KEYS, MINIGAME_LABELS,
)

SCAVENGE_CD_KEY = "scavenge"
DEFAULT_SCAVENGE_CD = 1800  # 30 minutes


def load_pools(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "scavenge_pools.json", {})


def save_pools(gid: int, data: dict):
    save_json(get_data_dir(gid) / "scavenge_pools.json", data)


def load_scavenge_channels(gid: int) -> dict:
    return load_json(get_data_dir(gid) / "scavenge_channels.json", {})


def save_scavenge_channels(gid: int, data: dict):
    save_json(get_data_dir(gid) / "scavenge_channels.json", data)


def _pools_embed(gid: int) -> discord.Embed:
    pools = load_pools(gid)
    embed = discord.Embed(title="🌿 หาของ — เลือกหมวด", color=EMBED_COLOR)
    if not pools:
        embed.description = "ยังไม่มีหมวดหาของ"
        return embed
    for pid, pool in pools.items():
        items_count = len(pool.get("items", []))
        embed.add_field(
            name=f"{pool.get('emoji','📦')} {pool.get('name', pid)}",
            value=pool.get("description", "")[:100] + f"\n({items_count} ไอเทมใน Pool)",
            inline=True,
        )
    return embed


def _weighted_choice(items: list) -> dict | None:
    if not items:
        return None
    weights = [max(1, it.get("weight", 1)) for it in items]
    return random.choices(items, weights=weights, k=1)[0]


# ── /scavenge command ─────────────────────────────────────────────────────────

@bot.tree.command(name="scavenge", description="ออกหาของในพื้นที่ต่างๆ")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_scavenge(ix: discord.Interaction):
    gid = ix.guild_id
    uid = ix.user.id

    # Check channel restriction
    ch_cfg = load_scavenge_channels(gid)
    if ch_cfg:
        allowed = {int(cid) for cid in ch_cfg.get("allowed", [])}
        if allowed and ix.channel_id not in allowed:
            ch_list = " ".join(f"<#{c}>" for c in allowed)
            await ix.response.send_message(
                f"ใช้คำสั่งนี้ในห้องที่กำหนดเท่านั้น: {ch_list}", ephemeral=True
            )
            return

    # Check player exists
    players = load_players(gid)
    if str(uid) not in players:
        await ix.response.send_message(
            embed=discord.Embed(
                description="ต้องสร้างตัวละครก่อน ใช้ `/orion`", color=discord.Color.red()
            ),
            ephemeral=True,
        )
        return

    # Check cooldown
    cfg       = load_config(gid)
    cd_secs   = cfg.get("scavenge_cooldown", DEFAULT_SCAVENGE_CD)
    remaining = cooldown_remaining(gid, uid, SCAVENGE_CD_KEY)
    if remaining > 0:
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"⏳ คูลดาวน์: **{format_cooldown(remaining)}**",
                color=0xF59E0B,
            ),
            ephemeral=True,
        )
        return

    pools = load_pools(gid)
    if not pools:
        await ix.response.send_message("ยังไม่มีพื้นที่หาของ", ephemeral=True)
        return

    embed = _pools_embed(gid)
    view  = ScavengeMenuView(uid, gid, cd_secs)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


class ScavengeMenuView(discord.ui.View):
    def __init__(self, uid: int, gid: int, cd_secs: int):
        super().__init__(timeout=60)
        self.uid     = uid
        self.gid     = gid
        self.cd_secs = cd_secs
        self._build()

    def _build(self):
        self.clear_items()
        pools = load_pools(self.gid)
        if not pools:
            return
        opts = [
            discord.SelectOption(
                label=pool.get("name", pid)[:100],
                value=pid,
                emoji=pool.get("emoji") or None,
                description=pool.get("description", "")[:100] or None,
            )
            for pid, pool in pools.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือกหมวดที่จะหา…", options=opts, row=0)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        if ix.user.id != self.uid:
            await ix.response.send_message("นี่ไม่ใช่เซสชันของคุณ", ephemeral=True)
            return
        pid   = ix.data["values"][0]
        pools = load_pools(self.gid)
        pool  = pools.get(pid)
        if not pool:
            await ix.response.send_message("ไม่พบหมวดนี้", ephemeral=True)
            return

        # Run a random minigame from this pool's list
        mg_list = pool.get("minigames", MINIGAME_KEYS)
        key     = random.choice(mg_list) if mg_list else None

        embed_start = discord.Embed(
            title=f"🌿 กำลังหาของ — {pool.get('name', pid)}",
            description="เล่นมินิเกมเพื่อได้ไอเทม!",
            color=EMBED_COLOR,
        )
        self.clear_items()
        await ix.response.edit_message(embed=embed_start, view=self)

        won = await run_minigame(ix, key)
        set_cooldown(self.gid, self.uid, SCAVENGE_CD_KEY, self.cd_secs)

        if won:
            pool_items = pool.get("items", [])
            if pool_items:
                chosen = _weighted_choice(pool_items)
                item_id = chosen.get("id", "unknown")
                qty     = chosen.get("qty", 1)

                # Add to inventory
                players = load_players(self.gid)
                p = players.get(str(self.uid), {})
                inv = p.setdefault("inventory", {})
                inv[item_id] = inv.get(item_id, 0) + qty
                players[str(self.uid)] = p
                save_players(self.gid, players)

                rarity  = chosen.get("rarity", "")
                catalog = load_items_catalog(self.gid)
                name    = catalog.get(item_id, {}).get("name", item_id)
                result  = f"✅ พบ **{name}** ×{qty}{' (' + rarity + ')' if rarity else ''}!"
                color   = discord.Color.green()
            else:
                result = "✅ ผ่านมินิเกมแต่ยังไม่มีไอเทมใน Pool"
                color  = 0xF59E0B
        else:
            result = f"❌ ไม่พบอะไร คูลดาวน์: {format_cooldown(self.cd_secs)}"
            color  = discord.Color.red()

        try:
            await ix.edit_original_response(
                embed=discord.Embed(
                    title="🌿 ผลการหาของ",
                    description=result,
                    color=color,
                ),
                view=None,
            )
        except Exception:
            pass


# ── /scavenge-admin command ───────────────────────────────────────────────────

@bot.tree.command(name="scavenge-admin", description="[Admin] จัดการระบบหาของ")
@app_commands.guilds(*GUILD_OBJECTS)
async def cmd_scavenge_admin(ix: discord.Interaction):
    if not ix.user.guild_permissions.administrator:
        await ix.response.send_message("Admin only.", ephemeral=True)
        return
    gid   = ix.guild_id
    cfg   = load_config(gid)
    embed = _scavenge_admin_embed(gid, cfg)
    view  = ScavengeAdminView(gid)
    await ix.response.send_message(embed=embed, view=view, ephemeral=True)


def _scavenge_admin_embed(gid: int, cfg: dict) -> discord.Embed:
    cd    = cfg.get("scavenge_cooldown", DEFAULT_SCAVENGE_CD)
    pools = load_pools(gid)
    embed = discord.Embed(title="🌿 Scavenge Admin", color=EMBED_COLOR)
    embed.add_field(name="คูลดาวน์", value=format_cooldown(cd), inline=True)
    embed.add_field(name="จำนวน Pool", value=str(len(pools)), inline=True)
    return embed


class ScavengeAdminView(discord.ui.View):
    def __init__(self, gid: int):
        super().__init__(timeout=300)
        self.gid = gid

    @discord.ui.button(label="⏱️ ตั้งคูลดาวน์", style=discord.ButtonStyle.secondary, row=0)
    async def btn_cd(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(SetScavengeCooldownModal(self.gid))

    @discord.ui.button(label="➕ เพิ่ม Pool", style=discord.ButtonStyle.success, row=0)
    async def btn_add_pool(self, ix: discord.Interaction, _: discord.ui.Button):
        await ix.response.send_modal(AddPoolModal(self.gid))

    @discord.ui.button(label="🗑️ ลบ Pool", style=discord.ButtonStyle.danger, row=0)
    async def btn_del_pool(self, ix: discord.Interaction, _: discord.ui.Button):
        pools = load_pools(self.gid)
        if not pools:
            await ix.response.send_message("ไม่มี Pool", ephemeral=True)
            return
        opts = [
            discord.SelectOption(label=pool.get("name", pid)[:100], value=pid)
            for pid, pool in pools.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือก Pool ที่จะลบ…", options=opts)

        async def _del(ix2: discord.Interaction):
            pools2 = load_pools(self.gid)
            pools2.pop(ix2.data["values"][0], None)
            save_pools(self.gid, pools2)
            await ix2.response.send_message(
                embed=discord.Embed(description="🗑️ ลบ Pool แล้ว", color=EMBED_COLOR),
                ephemeral=True,
            )

        sel.callback = _del
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="🎁 ตั้งไอเทมใน Pool", style=discord.ButtonStyle.primary, row=1)
    async def btn_items(self, ix: discord.Interaction, _: discord.ui.Button):
        pools = load_pools(self.gid)
        if not pools:
            await ix.response.send_message("ไม่มี Pool", ephemeral=True)
            return
        opts = [
            discord.SelectOption(label=pool.get("name", pid)[:100], value=pid)
            for pid, pool in pools.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือก Pool…", options=opts)

        async def _pick(ix2: discord.Interaction):
            pid = ix2.data["values"][0]
            await ix2.response.send_modal(AddPoolItemModal(self.gid, pid))

        sel.callback = _pick
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)

    @discord.ui.button(label="🎮 ตั้งมินิเกม", style=discord.ButtonStyle.secondary, row=1)
    async def btn_mg(self, ix: discord.Interaction, _: discord.ui.Button):
        pools = load_pools(self.gid)
        if not pools:
            await ix.response.send_message("ไม่มี Pool", ephemeral=True)
            return
        opts = [
            discord.SelectOption(label=pool.get("name", pid)[:100], value=pid)
            for pid, pool in pools.items()
        ][:25]
        sel = discord.ui.Select(placeholder="เลือก Pool…", options=opts)

        async def _pick(ix2: discord.Interaction):
            pid = ix2.data["values"][0]
            view2 = SetPoolMinigamesView(self.gid, pid)
            embed = discord.Embed(
                title="🎮 ตั้งมินิเกมของ Pool",
                description="เลือกมินิเกมที่ใช้ใน Pool นี้ (สุ่มจากที่เลือก):",
                color=EMBED_COLOR,
            )
            await ix2.response.send_message(embed=embed, view=view2, ephemeral=True)

        sel.callback = _pick
        v = discord.ui.View(timeout=60)
        v.add_item(sel)
        await ix.response.send_message(view=v, ephemeral=True)


class SetScavengeCooldownModal(discord.ui.Modal, title="ตั้งคูลดาวน์หาของ"):
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
        cfg["scavenge_cooldown"] = val
        save_config(self.gid, cfg)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ คูลดาวน์หาของ → {format_cooldown(val)}", color=EMBED_COLOR
            ),
            ephemeral=True,
        )


class AddPoolModal(discord.ui.Modal, title="เพิ่ม Pool หาของ"):
    pool_id   = discord.ui.TextInput(label="ID (ภาษาอังกฤษ)", max_length=30)
    pool_name = discord.ui.TextInput(label="ชื่อ Pool", max_length=60)
    pool_desc = discord.ui.TextInput(label="คำอธิบาย", max_length=200, required=False)
    pool_emoji = discord.ui.TextInput(label="Emoji", max_length=5, required=False)

    def __init__(self, gid: int):
        super().__init__()
        self.gid = gid

    async def on_submit(self, ix: discord.Interaction):
        pid   = self.pool_id.value.strip().replace(" ", "_").lower()
        pools = load_pools(self.gid)
        pools[pid] = {
            "name":        self.pool_name.value.strip(),
            "description": self.pool_desc.value.strip(),
            "emoji":       self.pool_emoji.value.strip() or "📦",
            "items":       [],
            "minigames":   list(MINIGAME_KEYS),
        }
        save_pools(self.gid, pools)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ เพิ่ม Pool **{self.pool_name.value}** แล้ว", color=EMBED_COLOR
            ),
            ephemeral=True,
        )


class AddPoolItemModal(discord.ui.Modal, title="เพิ่มไอเทมใน Pool"):
    item_id = discord.ui.TextInput(label="Item ID (จาก catalog)", max_length=40)
    weight  = discord.ui.TextInput(label="Weight (1-100, ค่ายิ่งสูงยิ่งหายาก=ต่ำ)", max_length=3)
    qty     = discord.ui.TextInput(label="จำนวน (qty)", max_length=3)
    rarity  = discord.ui.TextInput(label="Rarity (เช่น Common/Rare)", max_length=20, required=False)

    def __init__(self, gid: int, pool_id: str):
        super().__init__()
        self.gid     = gid
        self.pool_id = pool_id

    async def on_submit(self, ix: discord.Interaction):
        try:
            weight = max(1, int(self.weight.value.strip()))
            qty    = max(1, int(self.qty.value.strip()))
        except ValueError:
            await ix.response.send_message("ตัวเลขไม่ถูกต้อง", ephemeral=True)
            return
        pools = load_pools(self.gid)
        pool  = pools.get(self.pool_id, {})
        pool.setdefault("items", []).append({
            "id":     self.item_id.value.strip(),
            "weight": weight,
            "qty":    qty,
            "rarity": self.rarity.value.strip(),
        })
        pools[self.pool_id] = pool
        save_pools(self.gid, pools)
        await ix.response.send_message(
            embed=discord.Embed(
                description=f"✅ เพิ่ม `{self.item_id.value}` ใน Pool แล้ว", color=EMBED_COLOR
            ),
            ephemeral=True,
        )


class SetPoolMinigamesView(discord.ui.View):
    def __init__(self, gid: int, pool_id: str):
        super().__init__(timeout=120)
        self.gid     = gid
        self.pool_id = pool_id
        pools        = load_pools(gid)
        current      = set(pools.get(pool_id, {}).get("minigames", MINIGAME_KEYS))
        opts = [
            discord.SelectOption(
                label=MINIGAME_LABELS.get(k, k)[:100],
                value=k,
                default=k in current,
            )
            for k in MINIGAME_KEYS
        ]
        sel = discord.ui.Select(
            placeholder="เลือกมินิเกม…",
            options=opts,
            min_values=1,
            max_values=len(MINIGAME_KEYS),
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, ix: discord.Interaction):
        selected = ix.data["values"]
        pools    = load_pools(self.gid)
        if self.pool_id in pools:
            pools[self.pool_id]["minigames"] = selected
            save_pools(self.gid, pools)
        await ix.response.send_message(
            embed=discord.Embed(description="✅ บันทึกมินิเกมแล้ว", color=EMBED_COLOR),
            ephemeral=True,
        )
