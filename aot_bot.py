"""
Attack on Titan Discord Bot — main entry point.
Run: python aot_bot.py
Requires: DISCORD_TOKEN env var
"""
import os, sys, subprocess

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

import discord

@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    aot_shifter.start_tasks()
    aot_shop.start_shop_tasks()
    print(f"✅ Online as {bot.user} | {len(synced)} commands synced")

bot.run(os.environ["DISCORD_TOKEN"])
