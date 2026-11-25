import discord
from discord.ext import commands
import aiohttp
import os

class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="profile")
    async def profile(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        xf_url = os.getenv("XF_URL")
        xf_api_key = os.getenv("XF_API_KEY")
        headers = {"XF-Api-Key": xf_api_key}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{xf_url}/api/users?user_state=valid&q={target.id}", headers=headers) as resp:
                    if resp.status != 200:
                        await ctx.send("Аккаунт на форуме не привязан или не найден.")
                        return
                    data = await resp.json()
                    users = data.get("users", [])
                    if not users:
                        await ctx.send("Привязанный аккаунт XenForo не найден.")
                        return
                    
                    user = users[0]
                    custom_fields = user.get("custom_fields", {})
                    
                    embed = discord.Embed(title=f"Профиль игрока: {user.get('username')}", color=discord.Color.green())
                    embed.add_field(name="Уровень", value=custom_fields.-get("level", "Не указан"), inline=True)
                    embed.add_field(name="Фракция", value=custom_fields.get("fraction", "Нет"), inline=True)
                    embed.url = f"{xf_url}/index.php?members/{user.get('user_id')}/"
                    
                    await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"Ошибка получения профиля: {e}")

async def setup(bot):
    await bot.add_cog(Profile(bot))
