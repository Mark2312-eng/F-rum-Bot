import asyncio
import os
import aiohttp
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message

# Настройки бота и форума
TELEGRAM_BOT_TOKEN = "9041502480:AAED_rPS1t77kp-hX8dzZN_BulG7XKX43Vw"
XF_URL = "https://whg128846.samp.date/"
XF_API_KEY = "9GsxRycwYufhdiEP6gYHuNROQpT3ErYk" 
PORT = int(os.getenv("PORT", 10000))

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

# --- Health-check сервер для Render / BetterUptime ---
async def health_check(request):
    return web.Response(text="Telegram Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

# --- Хендлеры бота ---
@dp.message(F.text.startswith("/start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Здравствуйте! Это официальный бот проекта <b>VISE RUSSIA | MOSCOW</b>.\n\n"
        "Доступные команды:\n"
        "/punish <ник> — Проверить варны и баны игрока на форуме",
        parse_mode="HTML"
    )

@dp.message(F.text.startswith("/punish"))
async def cmd_punish(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("⚠️ Укажите ник игрока: <code>/punish &lt;ник&gt;</code>", parse_mode="HTML")
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
                    ban_status = "🔴 Забанен" if is_banned else "🟢 Не забанен"

                    text = (
                        f"📋 <b>Информация об игроке: {username}</b>\n\n"
                        f"🆔 ID на форуме: <code>{user_id}</code>\n"
                        f"🛡️ Статус бана: {ban_status}\n"
                        f"🔗 <a href='{XF_URL}/index.php?members/{user_id}/'>Открыть профиль на форуме</a>"
                    )
                    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            await message.answer(f"⚠️ Ошибка связи с API форума: {e}")

# --- Запуск приложения (Polling + Веб-сервер) ---
async def main():
    # Запускаем локальный веб-сервер для health-check в фоне
    asyncio.create_task(start_web_server())
    # Удаляем зависшие вебхуки и запускаем классический Polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
