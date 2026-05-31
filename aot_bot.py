"""
Attack on Titan Discord Bot — main entry point.
Run: python aot_bot.py
Requires: DISCORD_TOKEN env var
"""
import os, sys, subprocess, traceback

def _ensure(*pkgs):
    for p in pkgs:
        mod = p.split(">=")[0].split("[")[0].replace("-","_")
        try: __import__(mod)
        except ImportError:
            subprocess.run([sys.executable,"-m","pip","install",p,"--quiet"],check=False)

_ensure("discord.py>=2.6")

# Import modules — their decorators register all commands onto bot
from aot_bot_instance import bot
import aot_profile      # registers /profile
import aot_admin        # admin views (used by other modules)
import aot_items        # registers /item-admin, /items
import aot_shifter      # registers /shifter group, background tasks
import aot_set          # registers /set profile, /set banner
import aot_config       # registers /config
import aot_announcement # registers /paradis-announcement
import aot_shop         # registers /shop-setup, /shop-config, /shop
import aot_economy      # registers /balance
import aot_logs         # registers /logs-setup
import aot_mission      # registers /mission group
import aot_job          # registers /job, /job-owner, /job-admin
import aot_xp           # registers /xp
import aot_squad        # registers /squad
import aot_mindless     # registers /mindless, /mindless-inject
import aot_backup       # registers /backup

import discord
from discord.ext import tasks
from aot_shared import (
    load_config, load_players, save_players,
    load_config as _lc, assign_roles, remove_old_roles, log_event,
)


@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    aot_shifter.start_tasks()
    aot_shop.start_shop_tasks()
    aot_job.start_job_tasks()
    role_sync_task.start()
    print(f"✅ Online as {bot.user} | {len(synced)} commands synced")


# ── Global error reporting ────────────────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(ix: discord.Interaction, error: discord.app_commands.AppCommandError):
    cfg    = load_config(ix.guild_id) if ix.guild_id else {}
    ch_id  = cfg.get("error_log_channel")
    tb_str = traceback.format_exc()

    if ch_id and ix.guild:
        ch = ix.guild.get_channel(int(ch_id))
        if ch:
            try:
                v = discord.ui.LayoutView(timeout=None)
                v.add_item(discord.ui.Container(discord.ui.TextDisplay(
                    f"**⚠️ Command Error**\n"
                    f"User: <@{ix.user.id}> | Command: {ix.command.name if ix.command else '?'}\n"
                    f"```{str(error)[:500]}```"
                )))
                await ch.send(view=v)
            except Exception:
                pass

    if not ix.response.is_done():
        try:
            await ix.response.send_message(
                "An error occurred. Admins have been notified.", ephemeral=True)
        except Exception:
            pass

    print(f"[ERROR] {ix.command} — {error}\n{tb_str[:500]}")


# ── Role auto-sync task ───────────────────────────────────────────────────────

@tasks.loop(minutes=30)
async def role_sync_task():
    for guild in bot.guilds:
        gid     = guild.id
        cfg     = load_config(gid)
        players = load_players(gid)
        for uid, player in players.items():
            member = guild.get_member(int(uid))
            if not member:
                continue
            try:
                await assign_roles(member, player, cfg)
            except Exception:
                pass


bot.run(os.environ["DISCORD_TOKEN"])
