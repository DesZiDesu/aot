"""Orion Discord Bot — main entry point.
Run: python bot.py
Requires: ORION_TOKEN or DISCORD_TOKEN env var.
"""
import os
import sys
import subprocess
import traceback
from pathlib import Path

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
from core.instance import bot
from core.shared import ORION_GUILD_ID, GUILD2_ID

# Import all cogs — decorators register commands onto bot
import cogs.profile
import cogs.stats
import cogs.economy
import cogs.shop
import cogs.scavenge
import cogs.missions
import cogs.creation
import cogs.config


@bot.event
async def on_ready():
    for gid in (ORION_GUILD_ID, GUILD2_ID):
        try:
            synced = await bot.tree.sync(guild=discord.Object(id=gid))
            print(f"  Synced {len(synced)} commands to guild {gid}")
        except Exception as e:
            print(f"  Failed to sync guild {gid}: {e}")
    print(f"✅ Orion online as {bot.user}")


@bot.tree.error
async def on_app_command_error(ix: discord.Interaction, error: discord.app_commands.AppCommandError):
    tb = traceback.format_exc()
    print(f"[error] {ix.command}: {error}\n{tb}")
    try:
        embed = discord.Embed(
            title="⚠️ เกิดข้อผิดพลาด",
            description=str(error)[:500],
            color=discord.Color.red(),
        )
        if ix.response.is_done():
            await ix.followup.send(embed=embed, ephemeral=True)
        else:
            await ix.response.send_message(embed=embed, ephemeral=True)
    except Exception:
        pass


if __name__ == "__main__":
    token = os.environ.get("ORION_TOKEN") or os.environ.get("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Set ORION_TOKEN or DISCORD_TOKEN environment variable")
    bot.run(token)
