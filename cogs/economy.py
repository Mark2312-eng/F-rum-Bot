import discord
from discord.ext import commands
import aiohttp
import os
import random

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="daily")
    async def daily(self, ctx):
        await ctx.send(f"{ctx.author.mention}, вы успешно забрали ежедневный бонус в размере 50 баллов!")

    @commands.command(name="casino")
    async def casino(self, ctx, amount: int = None):
        if not amount or amount <= 10:
            await ctx.send("Укажите корректную сумму ставок (минимум 10 баллов).")
            return
        
        outcome = random.choice([True, False])
        if outcome:
            await ctx.send(f"Поздравляем, {ctx.author.mention}! Вы выиграли {amount * 2} баллов!")
        else:
            await ctx.send(f"К сожалению, {ctx.author.mention}, вы проиграли {amount} баллов.")

async def setup(bot):
    await bot.add_cog(Economy(bot))
