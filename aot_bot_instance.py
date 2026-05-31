"""AoT integration — uses orion_bot's bot instance + locked to GUILD2 only."""
import sys

_orion_bot_mod = sys.modules.get("orion_bot") or sys.modules.get("__main__")
if _orion_bot_mod is None or not hasattr(_orion_bot_mod, "bot"):
    raise ImportError("aot modules must be imported from orion_bot.py")

bot         = _orion_bot_mod.bot
GUILD2_ID   = _orion_bot_mod.GUILD2_ID
GUILD2_OBJ  = _orion_bot_mod._GUILD2_OBJ


def guild2_only(interaction) -> bool:
    """check: command อนุญาตเฉพาะ GUILD2"""
    return bool(interaction.guild and interaction.guild.id == GUILD2_ID)
