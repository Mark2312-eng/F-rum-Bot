"""Telegram bot for querying player moderation status on a XenForo forum."""

import asyncio
import logging
import os
from html import escape
from urllib.parse import urljoin

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()

LOGGER = logging.getLogger(__name__)
PORT = int(os.getenv("PORT", "10000"))
FORUM_URL = os.getenv("XF_URL", "https://example.com").rstrip("/") + "/"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)


def build_player_message(username: str, user_id: int, is_banned: bool) -> str:
    """Build an HTML-safe response containing the player's moderation status."""
    ban_status = "🔴 Забанен" if is_banned else "🟢 Не забанен"
    profile_url = urljoin(FORUM_URL, f"index.php?members/{user_id}/")
    return (
        f"📋 <b>Информация об игроке: {escape(username)}</b>\n\n"
        f"🆔 ID на форуме: <code>{user_id}</code>\n"
        f"🛡️ Статус бана: {ban_status}\n"
        f'🔗 <a href="{escape(profile_url, quote=True)}">'
        "Открыть профиль на форуме</a>"
    )


async def health_check(_request: web.Request) -> web.Response:
    """Return a lightweight health-check response."""
    return web.Response(text="Telegram Bot is running!")


async def run_web_server() -> None:
    """Run the health-check server and always release its resources."""
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()

    try:
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        LOGGER.info("Health-check server started on port %s", PORT)
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def find_forum_user(
    session: aiohttp.ClientSession, username: str, api_key: str
) -> tuple[int | None, dict | None]:
    """Look up a forum user and return their ID and full profile."""
    headers = {"XF-Api-Key": api_key}
    lookup_url = urljoin(FORUM_URL, "api/users/find-name")

    async with session.get(
        lookup_url,
        params={"username": username},
        headers=headers,
    ) as response:
        if response.status == 404:
            return None, None
        response.raise_for_status()
        lookup_data = await response.json()

    user = lookup_data.get("user")
    if not user or user.get("user_id") is None:
        return None, None

    user_id = int(user["user_id"])
    profile_url = urljoin(FORUM_URL, f"api/users/{user_id}")

    async with session.get(profile_url, headers=headers) as response:
        response.raise_for_status()
        profile_data = await response.json()

    return user_id, profile_data.get("full", {})


async def cmd_start(message: Message) -> None:
    await message.answer(
        "👋 Здравствуйте! Это официальный бот проекта "
        "<b>VISE RUSSIA | MOSCOW</b>.\n\n"
        "Доступные команды:\n"
        "/punish <ник> — Проверить статус бана игрока на форуме",
        parse_mode="HTML",
    )


async def cmd_punish(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "⚠️ Укажите ник игрока: <code>/punish &lt;ник&gt;</code>",
            parse_mode="HTML",
        )
        return

    api_key = os.getenv("XF_API_KEY")
    if not api_key:
        LOGGER.error("XF_API_KEY is not configured")
        await message.answer("⚠️ Сервис временно недоступен: не настроен API форума.")
        return

    username = args[1].strip()
    try:
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            user_id, profile = await find_forum_user(session, username, api_key)

        if user_id is None or profile is None:
            await message.answer("❌ Пользователь на форуме не найден.")
            return

        response_text = build_player_message(
            username=username,
            user_id=user_id,
            is_banned=bool(profile.get("is_banned", False)),
        )
        await message.answer(
            response_text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        LOGGER.warning("Forum API request failed: %s", type(exc).__name__)
        await message.answer("⚠️ Не удалось получить данные форума. Попробуйте позже.")
    except Exception:
        LOGGER.exception("Unexpected error while processing /punish")
        await message.answer("⚠️ Произошла внутренняя ошибка. Попробуйте позже.")


def create_dispatcher() -> Dispatcher:
    """Configure and return the Telegram dispatcher."""
    dispatcher = Dispatcher()
    dispatcher.message.register(cmd_start, F.text.startswith("/start"))
    dispatcher.message.register(cmd_punish, F.text.startswith("/punish"))
    return dispatcher


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing. Set it in the environment or .env file."
        )

    bot = Bot(token=token)
    dispatcher = create_dispatcher()
    web_task = asyncio.create_task(run_web_server(), name="health-check-server")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        web_task.cancel()
        await asyncio.gather(web_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
