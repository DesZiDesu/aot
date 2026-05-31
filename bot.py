"""
Attack on Titan Discord Bot — main entry point.
Run: python bot.py
Requires: DISCORD_TOKEN env var
"""
import os, sys, subprocess, traceback
from pathlib import Path

# Ensure project root is on the path so `core` and `cogs` packages resolve
sys.path.insert(0, str(Path(__file__).parent))


def _ensure(*pkgs):
    for p in pkgs:
        mod = p.split(">=")[0].split("[")[0].replace("-", "_")
        try:
            __import__(mod)
        except ImportError:
            subprocess.run([sys.executable, "-m", "pip", "install", p, "--quiet"], check=False)


_ensure("discord.py>=2.6")

import discord
from discord.ext import tasks

from core.instance import bot
from core.shared import load_config, load_players, save_players, assign_roles, remove_old_roles, log_event

# Import cogs — their decorators register all commands onto bot
import cogs.profile       # /profile
import cogs.admin         # /admin
import cogs.items         # /item-admin, /items
import cogs.shifter       # /shifter group
import cogs.set_profile   # /set profile, /set banner
import cogs.config        # /config
import cogs.announcement  # /paradis-announcement
import cogs.shop          # /shop-setup, /shop-config, /shop
import cogs.economy       # /balance
import cogs.logs          # /logs-setup
import cogs.mission       # /mission
import cogs.job           # /job, /job-owner, /job-admin
import cogs.xp            # /xp
import cogs.squad         # /squad
import cogs.mindless      # /mindless, /mindless-inject, /mindless-revert
import cogs.backup        # /backup


@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    cogs.shifter.start_tasks()
    cogs.shop.start_shop_tasks()
    cogs.job.start_job_tasks()
    role_sync_task.start()
    print(f"✅ Online as {bot.user} | {len(synced)} commands synced")


# ── Global error reporting ────────────────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(ix: discord.Interaction, error: discord.app_commands.AppCommandError):
    cfg   = load_config(ix.guild_id) if ix.guild_id else {}
    ch_id = cfg.get("error_log_channel")
    tb    = traceback.format_exc()

    if ch_id and ix.guild:
        ch = ix.guild.get_channel(int(ch_id))
        if ch:
            try:
                embed = discord.Embed(
                    title="⚠️ Command Error",
                    color=0xFF0000,
                    description=(
                        f"**User:** <@{ix.user.id}>\n"
                        f"**Command:** `{ix.command.name if ix.command else '?'}`\n"
                        f"```{str(error)[:500]}```"
                    ),
                )
                await ch.send(embed=embed)
            except Exception:
                pass

    if not ix.response.is_done():
        try:
            await ix.response.send_message(
                "An error occurred. Admins have been notified.", ephemeral=True
            )
        except Exception:
            pass

    print(f"[ERROR] {ix.command} — {error}\n{tb[:500]}")


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
