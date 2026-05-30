"""Single bot instance imported by all modules."""
import discord
from discord.ext import commands

intents = discord.Intents.default()
intents.members = True
intents.message_content = False

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
