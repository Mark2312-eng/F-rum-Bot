"""Telegram bot for querying player information on a XenForo forum."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiohttp import web
from dotenv import load_dotenv

from database import database
from moderation import moderate_message, mute_member, owner_summary, register_group, show_moderation_log, unmute_member, warn_member
from group_settings import apply_setting_callback, show_group_settings
from game import claim_daily_reward, handle_game_callback, show_achievements, show_game_profile, show_leaderboard
from work import handle_work_callback, show_jobs, show_work
from organizations import handle_org_callback, manage_family, manage_faction, show_factions
from economy import handle_economy_callback, show_garage, show_inventory, show_properties, show_shop
from city import handle_phone_callback, manage_city_event, show_city, show_events, show_phone, show_places
from quests import handle_quest_callback, show_quests, show_reputation
from tournaments import manage_tournament, show_tournaments
from government import manage_government
from service import manage_service

load_dotenv()

LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 10000
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)


def get_port(value: str | None = None) -> int:
    """Parse and validate the HTTP listening port."""
    raw_port = value if value is not None else os.getenv("PORT", str(DEFAULT_PORT))
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("PORT must be an integer between 1 and 65535") from exc

    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return port


def get_forum_url(value: str | None = None) -> str:
    """Validate XF_URL and normalize it as a directory URL."""
    raw_url = value if value is not None else os.getenv("XF_URL", "")
    raw_url = raw_url.strip()
    parsed = urlsplit(raw_url)

    try:
        valid_port = parsed.port
    except ValueError as exc:
        raise ValueError("XF_URL contains an invalid port") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "XF_URL must be an absolute http(s) URL without credentials, "
            "query, or fragment"
        )

    del valid_port
    return raw_url.rstrip("/") + "/"


def build_player_message(
    username: str, user_id: int, is_banned: bool, forum_url: str
) -> str:
    """Build an HTML-safe response containing the player's moderation status."""
    ban_status = "🔴 Забанен" if is_banned else "🟢 Не забанен"
    profile_url = urljoin(forum_url, f"index.php?members/{user_id}/")
    return (
        f"📋 <b>Информация об игроке: {escape(username)}</b>\n\n"
        f"🆔 ID на форуме: <code>{user_id}</code>\n"
        f"🛡️ Статус бана: {ban_status}\n"
        f'🔗 <a href="{escape(profile_url, quote=True)}">'
        "Открыть профиль на форуме</a>"
    )


def format_forum_date(value: object) -> str | None:
    """Format a XenForo Unix timestamp without failing on missing data."""
    if isinstance(value, bool):
        return None
    try:
        timestamp = int(value)
        if timestamp <= 0:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%d.%m.%Y %H:%M UTC"
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def build_profile_message(
    requested_name: str, user_id: int, profile: dict, forum_url: str
) -> str:
    """Build a profile summary using only fields returned by XenForo."""
    username = str(profile.get("username") or requested_name)
    title = profile.get("user_title")
    profile_url = urljoin(forum_url, f"index.php?members/{user_id}/")
    lines = [
        f"👤 <b>Профиль игрока: {escape(username)}</b>",
        f"🆔 ID: <code>{user_id}</code>",
    ]

    if title:
        lines.append(f"🏷️ Статус: {escape(str(title))}")

    registered = format_forum_date(profile.get("register_date"))
    if registered:
        lines.append(f"📅 Регистрация: {registered}")

    if profile.get("message_count") is not None:
        lines.append(f"💬 Сообщений: <b>{escape(str(profile['message_count']))}</b>")

    if profile.get("trophy_points") is not None:
        lines.append(f"🏆 Очки достижений: <b>{escape(str(profile['trophy_points']))}</b>")

    last_activity = format_forum_date(profile.get("last_activity"))
    if last_activity:
        lines.append(f"🕒 Последняя активность: {last_activity}")

    lines.append(
        "🛡️ Наказание: "
        + ("🔴 Забанен" if bool(profile.get("is_banned", False)) else "🟢 Не забанен")
    )
    lines.extend(
        [
            "",
            f'🔗 <a href="{escape(profile_url, quote=True)}">Открыть профиль на форуме</a>',
        ]
    )
    return "\n".join(lines)


def build_main_keyboard(forum_url: str) -> InlineKeyboardMarkup:
    """Create the main navigation keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Игровой профиль", callback_data="game:profile")],
            [InlineKeyboardButton(text="⚙️ Панель владельца", callback_data="owner_panel")],
            [InlineKeyboardButton(text="🌐 Открыть форум", url=forum_url)],
        ]
    )


async def health_check(_request: web.Request) -> web.Response:
    """Return a lightweight health-check response."""
    return web.Response(text="Telegram Bot is running!")


async def start_web_server(port: int) -> web.AppRunner:
    """Start the health server or raise immediately if binding fails."""
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app, access_log=LOGGER)
    await runner.setup()

    try:
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
    except BaseException:
        await runner.cleanup()
        raise

    LOGGER.info("Health-check server is listening on 0.0.0.0:%s", port)
    return runner


async def find_forum_user(
    session: aiohttp.ClientSession,
    forum_url: str,
    username: str,
    api_key: str,
) -> tuple[int | None, dict | None]:
    """Look up a forum user and return their ID and profile data."""
    headers = {"XF-Api-Key": api_key, "Accept": "application/json"}
    lookup_url = urljoin(forum_url, "api/users/find-name")

    async with session.get(
        lookup_url,
        params={"username": username},
        headers=headers,
    ) as response:
        if response.status == 404:
            return None, None
        response.raise_for_status()
        lookup_data = await response.json()

    if not isinstance(lookup_data, dict):
        raise ValueError("Unexpected XenForo user lookup response")

    user = lookup_data.get("user")
    if not isinstance(user, dict):
        return None, None

    raw_user_id = user.get("user_id")
    if isinstance(raw_user_id, bool):
        return None, None
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return None, None
    if user_id <= 0:
        return None, None

    profile_url = urljoin(forum_url, f"api/users/{user_id}")
    async with session.get(profile_url, headers=headers) as response:
        if response.status == 404:
            return None, None
        response.raise_for_status()
        profile_data = await response.json()

    if not isinstance(profile_data, dict):
        raise ValueError("Unexpected XenForo profile response")

    profile = profile_data.get("user")
    if not isinstance(profile, dict):
        raise ValueError("XenForo profile response does not contain a user object")

    return user_id, profile


def build_stats_message(stats: dict, forum_url: str) -> str:
    """Format the official XenForo site statistics response."""
    totals = stats.get("totals")
    totals = totals if isinstance(totals, dict) else stats
    online = stats.get("online")
    online = online if isinstance(online, dict) else {}

    def number(value: object) -> str | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return f"{parsed:,}".replace(",", " ")

    labels = (("threads", "🧵 Тем"), ("messages", "💬 Сообщений"), ("users", "👥 Пользователей"))
    lines = ["📊 <b>Статистика форума VISE RUSSIA</b>", ""]
    for key, label in labels:
        value = number(totals.get(key))
        if value is not None:
            lines.append(f"{label}: <b>{value}</b>")

    online_total = number(online.get("total"))
    if online_total is not None:
        lines.extend(["", f"🟢 Сейчас онлайн: <b>{online_total}</b>"])
        members = number(online.get("members"))
        guests = number(online.get("guests"))
        if members is not None:
            lines.append(f"   • Участников: {members}")
        if guests is not None:
            lines.append(f"   • Гостей: {guests}")

    latest_user = stats.get("latest_user")
    if len(lines) == 2 and not (isinstance(latest_user, dict) and latest_user.get("username")):
        return "⚠️ Форум не вернул доступные статистические данные."
    if isinstance(latest_user, dict) and latest_user.get("username"):
        lines.extend(["", f"🆕 Последний участник: <b>{escape(str(latest_user['username']))}</b>"])
    lines.extend(["", f'<a href="{escape(forum_url, quote=True)}">Открыть форум</a>'])
    return "\n".join(lines)


async def fetch_forum_stats(session: aiohttp.ClientSession, forum_url: str, api_key: str) -> dict:
    """Retrieve site statistics and log safe metadata if a firewall intercepts the API."""
    headers = {"XF-Api-Key": api_key, "Accept": "application/json"}
    request_url = urljoin(forum_url, "api/stats/")
    async with session.get(request_url, headers=headers, allow_redirects=True) as response:
        final_url = urlsplit(str(response.url))
        content_type = response.headers.get("Content-Type", "")
        location = response.headers.get("Location", "")
        location_url = urlsplit(location) if location else None
        LOGGER.info(
            "XenForo stats HTTP response: status=%s content_type=%r final_host=%r "
            "final_path=%r server=%r cf_ray_present=%s redirect_host=%r",
            response.status,
            content_type[:120],
            final_url.hostname,
            final_url.path[:180],
            response.headers.get("Server", "")[:80],
            bool(response.headers.get("CF-Ray")),
            location_url.hostname if location_url else None,
        )
        response.raise_for_status()
        if "json" not in content_type.lower():
            raise ValueError(
                f"XenForo stats endpoint returned non-JSON content type: {content_type[:120]!r}"
            )
        payload = await response.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected XenForo statistics response")
    return payload


async def send_forum_stats(message: Message) -> None:
    api_key = os.getenv("XF_API_KEY", "").strip()
    if not api_key:
        LOGGER.error("XF_API_KEY is not configured")
        await message.answer("⚠️ Статистика временно недоступна: не настроен API форума.")
        return
    try:
        forum_url = get_forum_url()
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            stats = await fetch_forum_stats(session, forum_url, api_key)
        await message.answer(build_stats_message(stats, forum_url), parse_mode="HTML", disable_web_page_preview=True)
    except (ValueError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
        LOGGER.warning("XenForo statistics request failed: %s: %s", type(exc).__name__, str(exc)[:200])
        await message.answer("⚠️ Не удалось получить статистику форума. Попробуйте позже.")
    except Exception:
        LOGGER.exception("Unexpected error while fetching forum statistics")
        await message.answer("⚠️ Не удалось получить статистику форума. Попробуйте позже.")


async def cmd_start(message: Message) -> None:
    try:
        forum_url = get_forum_url()
    except ValueError:
        LOGGER.exception("XF_URL configuration is invalid")
        await message.answer("⚠️ Сервис временно недоступен: неверно настроен адрес форума.")
        return

    await message.answer(
        "👋 <b>VISE RUSSIA | MOSCOW</b>\n\n"
        "Бот управления и модерации Telegram-групп.\n\n"
        "Добавьте бота в группу и выдайте права администратора.\n"
        "Владелец может открыть панель командой /owner.",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(forum_url),
    )


async def cmd_menu_callback(callback: CallbackQuery) -> None:
    """Handle menu shortcuts and clearly label features not released yet."""
    data = callback.data or ""
    messages = {
        "profile_help": "Чтобы открыть профиль, отправьте команду:\n/profile Ник",
        "punish_help": "Чтобы проверить статус наказания, отправьте команду:\n/punish Ник",
    }
    await callback.answer()
    if callback.message and data == "owner_panel":
        owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
        if callback.from_user.id != owner_id or owner_id <= 0:
            await callback.message.answer("⛔ Панель доступна только владельцу бота.")
        else:
            chat_count = await database.registered_chat_count()
            await callback.message.answer(owner_summary(owner_id, chat_count), parse_mode="HTML")
    elif callback.message and data in messages:
        await callback.message.answer(messages[data])


async def lookup_profile_for_message(message: Message) -> tuple[int, dict, str] | None:
    """Fetch a XenForo profile for a command argument."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return None

    api_key = os.getenv("XF_API_KEY", "").strip()
    if not api_key:
        LOGGER.error("XF_API_KEY is not configured")
        await message.answer("⚠️ Сервис временно недоступен: не настроен API форума.")
        return None

    try:
        forum_url = get_forum_url()
        username = args[1].strip()
        async with aiohttp.ClientSession(timeout=REQUEST_TIMEOUT) as session:
            user_id, profile = await find_forum_user(
                session, forum_url, username, api_key
            )
        if user_id is None or profile is None:
            await message.answer("❌ Пользователь на форуме не найден.")
            return None
        return user_id, profile, forum_url
    except ValueError:
        LOGGER.exception("XF_URL or XenForo response is invalid")
        await message.answer("⚠️ Не удалось получить данные форума. Проверьте настройки.")
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        LOGGER.warning("XenForo API request failed: %s", type(exc).__name__)
        await message.answer("⚠️ Не удалось получить данные форума. Попробуйте позже.")
    except Exception:
        LOGGER.exception("Unexpected error while looking up a forum profile")
        await message.answer("⚠️ Произошла внутренняя ошибка. Попробуйте позже.")
    return None


async def cmd_profile(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer("Укажите ник игрока: /profile Ник")
        return

    result = await lookup_profile_for_message(message)
    if result is None:
        return
    user_id, profile, forum_url = result
    await message.answer(
        build_profile_message(args[1].strip(), user_id, profile, forum_url),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def cmd_punish(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "⚠️ Укажите ник игрока: <code>/punish &lt;ник&gt;</code>",
            parse_mode="HTML",
        )
        return

    result = await lookup_profile_for_message(message)
    if result is None:
        return
    user_id, profile, forum_url = result
    response_text = build_player_message(
        username=str(profile.get("username") or args[1].strip()),
        user_id=user_id,
        is_banned=bool(profile.get("is_banned", False)),
        forum_url=forum_url,
    )
    await message.answer(
        response_text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def cmd_owner(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id <= 0 or not message.from_user or message.from_user.id != owner_id:
        await message.answer("⛔ Команда доступна только владельцу бота.")
        return
    chat_count = await database.registered_chat_count()
    await message.answer(owner_summary(owner_id, chat_count), parse_mode="HTML")


async def cmd_myid(message: Message) -> None:
    if message.from_user:
        await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>", parse_mode="HTML")


async def cmd_chats(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id <= 0 or not message.from_user or message.from_user.id != owner_id:
        await message.answer("⛔ Команда доступна только владельцу бота.")
        return
    chat_count = await database.registered_chat_count()
    await message.answer(f"Подключено групп: <b>{chat_count}</b>", parse_mode="HTML")


async def group_register_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await register_group(message, bot, owner_id)


async def group_settings_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_group_settings(message, bot, owner_id)


async def group_setting_callback(callback: CallbackQuery, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await apply_setting_callback(callback, bot, owner_id)


async def group_modlog_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_moderation_log(message, bot, owner_id)


async def group_moderation_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await moderate_message(message, bot, owner_id)


async def group_warn_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await warn_member(message, bot, owner_id)


async def group_mute_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await mute_member(message, bot, owner_id)


async def group_unmute_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await unmute_member(message, bot, owner_id)


def create_dispatcher() -> Dispatcher:
    """Configure and return the Telegram dispatcher."""
    dispatcher = Dispatcher()
    dispatcher.message.register(cmd_start, Command("start"))
    dispatcher.message.register(show_game_profile, Command("game"))
    dispatcher.message.register(claim_daily_reward, Command("daily"))
    dispatcher.message.register(show_leaderboard, Command("top"))
    dispatcher.message.register(show_achievements, Command("achievements"))
    dispatcher.message.register(show_jobs, Command("jobs"))
    dispatcher.message.register(show_work, Command("work"))
    dispatcher.message.register(show_factions, Command("factions"))
    dispatcher.message.register(manage_faction, Command("faction"))
    dispatcher.message.register(manage_family, Command("family"))
    dispatcher.message.register(show_shop, Command("shop"))
    dispatcher.message.register(show_inventory, Command("inventory"))
    dispatcher.message.register(show_properties, Command("property"))
    dispatcher.message.register(show_garage, Command("garage"))
    dispatcher.message.register(show_phone, Command("phone"))
    dispatcher.message.register(show_city, Command("city"))
    dispatcher.message.register(show_places, Command("places"))
    dispatcher.message.register(show_events, Command("events"))
    dispatcher.message.register(manage_city_event, Command("event"))
    dispatcher.message.register(show_quests, Command("quests"))
    dispatcher.message.register(show_reputation, Command("reputation"))
    dispatcher.message.register(show_tournaments, Command("tournaments"))
    dispatcher.message.register(manage_tournament, Command("tournament"))
    dispatcher.message.register(manage_government, Command("gov"))
    dispatcher.message.register(manage_service, Command("service"))
    dispatcher.message.register(cmd_profile, Command("profile"))
    dispatcher.message.register(cmd_punish, Command("punish"))
    dispatcher.message.register(cmd_owner, Command("owner"))
    dispatcher.message.register(cmd_myid, Command("myid"))
    dispatcher.message.register(cmd_chats, Command("chats"))
    dispatcher.message.register(group_register_handler, Command("connect", ignore_mention=True))
    dispatcher.message.register(group_settings_handler, Command("settings", ignore_mention=True))
    dispatcher.message.register(group_modlog_handler, Command("modlog", ignore_mention=True))
    dispatcher.message.register(group_warn_handler, Command("warn", ignore_mention=True))
    dispatcher.message.register(group_mute_handler, Command("mute", ignore_mention=True))
    dispatcher.message.register(group_unmute_handler, Command("unmute", ignore_mention=True))
    dispatcher.message.register(group_moderation_handler)
    dispatcher.callback_query.register(cmd_menu_callback, F.data == "owner_panel")
    dispatcher.callback_query.register(handle_game_callback, F.data.startswith("game:"))
    dispatcher.callback_query.register(handle_work_callback, F.data.startswith("work:"))
    dispatcher.callback_query.register(handle_org_callback, F.data.startswith("org:"))
    dispatcher.callback_query.register(handle_economy_callback, F.data.startswith("eco:"))
    dispatcher.callback_query.register(handle_phone_callback, F.data.startswith("phone:"))
    dispatcher.callback_query.register(handle_quest_callback, F.data.startswith("quest:"))
    dispatcher.callback_query.register(group_setting_callback, F.data.startswith("cfg:"))
    return dispatcher


async def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from the environment")

    try:
        port = get_port()
        forum_url = get_forum_url()
    except ValueError as exc:
        raise RuntimeError(f"Invalid application configuration: {exc}") from exc

    LOGGER.info("Using XenForo installation at %s", forum_url)
    bot = Bot(token=token)
    dispatcher = create_dispatcher()
    runner: web.AppRunner | None = None

    try:
        await database.connect()
        LOGGER.info("PostgreSQL connection established")
        runner = await start_web_server(port)
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        if runner is not None:
            await runner.cleanup()
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        LOGGER.info("Application stopped")
