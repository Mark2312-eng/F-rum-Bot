import discord
from discord.ext import commands
import os

class ModLogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        channel_id = int(os.getenv("DISCORD_MOD_LOGS_CHANNEL_ID", "0"))
        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(f"👤 Пользователь вошел на сервер: {member} ({member.id})")

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot:
            return
        channel_id = int(os.getenv("DISCORD_MOD_LOGS_CHANNEL_ID", "0"))
        channel = self.bot.get_channel(channel_id)
        if channel:
            await channel.send(f"🗑️ Удалено сообщение от **{message.author}** в канале {message.channel.mention}: {message.content}")

async def setup(bot):
    await bot.add_cog(ModLogs(bot))
