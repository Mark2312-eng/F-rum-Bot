import discord
from discord.ext import commands
import aiohttp
import os

class TicketModal(discord.ui.Modal, title="Создание жалобы"):
    target_nick = discord.ui.TextInput(label="Ник нарушителя", placeholder="Введите Nick_Name", required=True)
    reason = discord.ui.TextInput(label="Суть жалобы", style=discord.TextStyle.paragraph, placeholder="Опишите нарушение...", required=True)

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        
        xf_url = os.getenv("XF_URL")
        xf_api_key = os.getenv("XF_API_KEY")
        node_id = os.getenv("XF_COMPLAINT_NODE_ID", "1")

        headers = {"XF-Api-Key": xf_api_key}
        data = {
            "node_id": node_id,
            "title": f"Жалоба на игрока {self.target_nick.value}",
            "message": f"Отправитель Discord: {interaction.user} (ID: {interaction.user.id})\n\nСуть:\n{self.reason.value}"
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(f"{xf_url}/api/threads/", headers=headers, data=data) as resp:
                    if resp.status == 200:
                        res_json = await resp.json()
                        thread_id = res_json.get("thread", {}).get("thread_id")
                        thread_link = f"{xf_url}/index.php?threads/{thread_id}/"
                        await interaction.followup.send(f"Жалоба успешно создана на форуме: {thread_link}", ephemeral=True)
                    else:
                        await interaction.followup.send("Ошибка при создании темы на форуме через API.", ephemeral=True)
            except Exception as e:
                await interaction.followup.send(f"Произошла ошибка связи с API: {e}", ephemeral=True)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="report")
    async def report(self, ctx):
        modal = TicketModal(self.bot)
        await ctx.interaction.response.send_modal(modal) if ctx.interaction else await ctx.send("Используйте слэш-команду или вызовите модальное окно через взаимодействие.")

async def setup(bot):
    await bot.add_cog(Tickets(bot))
