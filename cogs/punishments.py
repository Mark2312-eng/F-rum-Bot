import discord
from discord.ext import commands
import aiohttp
import os

class Punishments(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="punish")
    async def punish(self, ctx, username: str = None):
        if not username:
            await ctx.send("Укажите ник игрока: `!punish <ник>`")
            return

        xf_url = os.getenv("XF_URL")
        xf_api_key = os.getenv("XF_API_KEY")
        headers = {"XF-Api-Key": xf_api_key}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{xf_url}/api/users/find-name?username={username}", headers=headers) as resp:
                    if resp.status != 200:
                        await ctx.send("Пользователь на форуме не найден.")
                        return
                    data = await resp.json()
                    user = data.get("user")
                    if not user:
                        await ctx.send("Пользователь не найден.")
                        return
                    
                    user_id = user.get("user_id")
                    
                    async with session.get(f"{xf_url}/api/users/{user_id}", headers=headers) as user_resp:
                        if user_resp.status != 200:
                            await ctx.send("Не удалось получить данные пользователя.")
                            return
                        user_data = await user_resp.json()
                        profile = user_data.get("full", {})

                        embed = discord.Embed(title=f"Информация о наказаниях: {username}", color=discord.Color.red())
                        embed.add_field(name="Активные варны", value=str(profile.get("custom_fields", {}).get("warns", "0/3")), inline=True)
                        embed.add_field(name="Бан", value=profile.get("is_banned", False) and "Забанен" "Активен" or "Отсутствует", inline=True)
                        
                        await ctx.send(embed=embed)
            except Exception as e:
                await ctx.send(f"Ошибка запроса к API: {e}")

async def setup(bot):
    await bot.add_cog(Punishments(bot))
