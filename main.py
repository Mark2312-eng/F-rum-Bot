import asyncio
import os
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
XF_URL = os.getenv("XF_URL")
XF_API_KEY = os.getenv("XF_API_KEY")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Health-check сервер для Render / BetterUptime ---
async def health_check(request):
    return web.Response(text="Telegram Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

# --- Хендлеры бота ---
@dp.message(F.text.startswith("/start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Здравствуйте! Это официальный бот проекта [b]VISE RUSSIA | MOSCOW[/b].\n\n"
        "Доступные команды:\n"
        "/punish <ник> — Проверить варны и баны игрока на форуме",
        parse_mode="HTML"
    )

@dp.message(F.text.startswith("/punish"))
async def cmd_punish(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажите ник игрока: `/punish <ник>`", parse_mode="Markdown")
        return
    
    username = args[1]
    headers = {"XF-Api-Key": XF_API_KEY}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"{XF_URL}/api/users/find-name?username={username}", headers=headers) as resp:
                if resp.status != 200:
                    await message.answer("❌ Пользователь на форуме не найден.")
                    return
                data = await resp.json()
                user = data.get("user")
                if not user:
                    await message.answer("❌ Пользователь не найден.")
                    return
                
                user_id = user.get("user_id")
                
                async with session.get(f"{XF_URL}/api/users/{user_id}", headers=headers) as user_resp:
                    if user_resp.status != 200:
                        await message.answer("❌ Не удалось получить данные профиля.")
                        return
                    user_data = await user_resp.json()
                    profile = user_data.get("full", {})
                    
                    is_banned = profile.get("is_banned", False)
                    ban_status = "🔴 Забанен" "Активен" if is_banned else "🟢 Не забанен"

                    text = (
                        f"📋 <b>Информация об игроке: {username}</b>\n\n"
                        f"🆔 ID на форуме: <code>{user_id}</code>\n"
                        f"🛡️ Статус бана: {ban_status}\n"
                        f"🔗 <a href='{XF_URL}/index.php?members/{user_id}/'>Открыть профиль на форуме</a>"
                    )
                    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            await message.answer(f"⚠️ Ошибка связи с API форума: {e}")

# --- Запуск приложения ---
async def main():
    # Запускаем веб-сервер в фоновой задаче
    asyncio.create_task(start_web_server())
    # Запускаем поллинг бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
