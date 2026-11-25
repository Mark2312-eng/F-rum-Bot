import asyncio
import os
import aiohttp
from aiohttp import web
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

async def load_extensions():
    initial_extensions = [
        "cogs.tickets",
        "cogs.punishments",
        "cogs.announcements",
        "cogs.profile",
        "cogs.economy",
        "cogs.mod_logs",
        "cogs.auto_roles"
    ]
    for ext in initial_extensions:
        try:
            await bot.load_extension(ext)
        except Exception as e:
            print(f"Failed to load extension {ext}: {e}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

async def main():
    async with bot:
        await load_extensions()
        await asyncio.create_task(start_web_server())
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
