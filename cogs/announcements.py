import discord
from discord.ext import commands, tasks
import aiohttp
import os

class Announcements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_thread_id = None
        self.check_news.start()

    def cog_unload(self):
        self.check_news.cancel()

    @tasks.loop(minutes=5)
    async def check_news(self):
        xf_url = os.getenv("XF_URL")
        xf_api_key = os.getenv("XF_API_KEY")
        news_node_id = os.getenv("XF_NEWS_NODE_ID", "2")
        channel_id = int(os.getenv("DISCORD_ANNOUNCE_CHANNEL_ID", "0"))

        if not channel_id:
            return

        headers = {"XF-Api-Key": xf_api_key}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{xf_url}/api/forums/{news_node_id}", headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        threads = data.get("threads", [])
                        if threads:
                            latest = threads[0]
                            t_id = latest.get("thread_id")
                            if self.last_thread_id is None:
                                self.last_thread_id = t_id
                                return
                            if t_id != self.last_thread_id:
                                self.last_thread_id = t_id
                                channel = self.bot.get_channel(channel_id)
                                if channel:
                                    embed = discord.Embed(
                                        title=latest.get("title"),
                                        url=f"{xf_url}/index.php?threads/{t_id}/",
                                        description="Появилась новая новость на форуме!",
                                        color=discord.Color.blue()
                                    )
                                    await channel.send(embed=embed)
            except Exception:
                pass

    @check_news.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Announcements(bot))
