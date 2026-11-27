"""Telegram moderation bot for VISE RUSSIA XenForo community."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import BotCommand, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiohttp import web
from dotenv import load_dotenv

from database import database
from moderation import ban_member, clear_warnings, kick_member, moderate_message, mute_member, owner_summary, purge_messages, register_group, show_moderation_log, show_moderation_stats, show_warnings, unban_member, unmute_member, warn_member
from group_settings import apply_setting_callback, show_group_settings
from advanced_moderation import blacklist_command, nickname_command, report_command, reportclose_command, reports_command, role_command

load_dotenv()

LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 10000
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
PENDING_INPUTS: dict[int, str] = {}


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


def build_main_keyboard(forum_url: str, is_owner: bool = False) -> InlineKeyboardMarkup:
    """Create a compact moderation-first navigation keyboard."""
    rows = [
        [InlineKeyboardButton(text="👤 Профиль форума", callback_data="menu:profile")],
        [InlineKeyboardButton(text="🛡 Проверить наказание", callback_data="menu:punish")],
        [InlineKeyboardButton(text="📊 Статистика форума", callback_data="menu:stats")],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton(text="⚙️ Панель владельца", callback_data="owner_panel")])
    rows.append([InlineKeyboardButton(text="🌐 Открыть форум", url=forum_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_section_keyboard(section: str = "moderation") -> InlineKeyboardMarkup:
    """Build the moderation navigation menu."""
    rows = [
        [InlineKeyboardButton(text="⚠️ Предупредить", callback_data="owner:warn")],
        [InlineKeyboardButton(text="🔇 Выдать мут", callback_data="owner:mute")],
        [InlineKeyboardButton(text="🔊 Снять мут", callback_data="owner:unmute")],
        [InlineKeyboardButton(text="⚙️ Настройки группы", callback_data="owner:settings")],
        [InlineKeyboardButton(text="📜 Журнал модерации", callback_data="owner:modlog")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_owner_keyboard() -> InlineKeyboardMarkup:
    """Owner-only controls; authorization is rechecked for every callback."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Сводка", callback_data="owner:summary"), InlineKeyboardButton(text="👥 Подключённые группы", callback_data="owner:chats")],
        [InlineKeyboardButton(text="🆔 Мой Telegram ID", callback_data="owner:myid")],
        [InlineKeyboardButton(text="⚙️ Настройки группы", callback_data="owner:settings"), InlineKeyboardButton(text="📜 Журнал модерации", callback_data="owner:modlog")],
        [InlineKeyboardButton(text="➕ Подключить эту группу", callback_data="owner:connect")],
        [InlineKeyboardButton(text="⚠️ Предупредить", callback_data="owner:warn"), InlineKeyboardButton(text="🔇 Мут 10 мин", callback_data="owner:mute")],
        [InlineKeyboardButton(text="🔊 Снять мут", callback_data="owner:unmute")],
        [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:home")],
    ])


async def health_check(_request: web.Request) -> web.Response:
    """Return a lightweight health-check response."""
    return web.Response(text="Telegram Bot is running!")


async def start_web_server(port: int) -> web.AppRunner:
    """Start the lightweight health-check server."""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
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
        "Профили форума, проверка наказаний и инструменты модерации доступны через кнопки.\n"
        "Команды: /help.",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(forum_url, is_owner=bool(message.from_user and message.from_user.id == int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0"))),
    )


async def cmd_help(message: Message) -> None:
    """List supported forum and moderation commands."""
    await message.answer(
        "🛡 <b>F-rum-Bot — команды</b>\\n\\n"
        "<b>Форум:</b>\\n"
        "/profile НИК — профиль XenForo\\n"
        "/punish НИК — статус наказания\\n"
        "/stats — статистика форума\\n\\n"
        "<b>Модерация группы:</b>\\n"
        "/warn ID — предупреждение\\n"
        "/warns ID — посмотреть предупреждения\\n"
        "/clearwarns ID — сбросить предупреждения\\n"
        "/mute ID — мут на 10 минут\\n"
        "/unmute ID — снять мут\\n"
        "/ban ID и /unban ID — блокировка и снятие блокировки\\n"
        "/kick ID — исключить участника\\n"
        "/purge N — удалить последние 1–100 сообщений\\n"
        "/modstats — статистика модерации за 7 дней\\n"
        "/settings — настройки антифлуда и ссылок\\n"
        "/modlog — журнал модерации\\n"
        "/report причина — пожаловаться на сообщение (ответом)\\n"
        "/reports — очередь жалоб\\n"
        "/reportclose ID — закрыть жалобу\\n"
        "/blacklist add/del/list — общий чёрный список\\n"
        "/nick set Имя или /nick ID — никнеймы группы\\n"
        "/role add/del/list — дополнительные модераторы\\n"
        "/connect — подключить группу (владелец бота).\\n\\n"
        "Команды модерации доступны владельцу и администраторам подключённой группы. "
        "Боту нужны права администратора.",
        parse_mode="HTML",
    )


async def cmd_menu_callback(callback: CallbackQuery) -> None:
    """Handle moderation menu navigation and owner actions."""
    await callback.answer()
    message = callback.message
    if message is None:
        return
    data = callback.data or ""
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    is_owner = owner_id > 0 and callback.from_user.id == owner_id

    if data == "menu:home":
        await message.answer(
            "Главное меню модерации:",
            reply_markup=build_main_keyboard(get_forum_url(), is_owner=is_owner),
        )
        return
    if data.startswith("menu:"):
        section = data.split(":", 1)[1]
        if section in {"profile", "punish"}:
            PENDING_INPUTS[callback.from_user.id] = section
            prompt = "Отправьте ник пользователя форума для поиска профиля." if section == "profile" else "Отправьте ник пользователя форума для проверки наказания."
            await message.answer(prompt)
        elif section == "stats":
            await send_forum_stats(message)
        else:
            await message.answer("Выберите инструмент модерации:", reply_markup=build_section_keyboard())
        return

    if data == "owner_panel" or data.startswith("owner:"):
        if not is_owner:
            await message.answer("⛔ Панель доступна только владельцу бота.")
            return
        if data == "owner_panel":
            count = await database.registered_chat_count()
            await message.answer(
                owner_summary(owner_id, count),
                parse_mode="HTML",
                reply_markup=build_owner_keyboard(),
            )
            return
        action = data.split(":", 1)[1]
        if action in {"warn", "mute", "unmute"}:
            if message.chat.type == "private":
                await message.answer(
                    "Откройте панель в подключённой группе и выберите действие там.",
                    reply_markup=build_owner_keyboard(),
                )
            else:
                PENDING_INPUTS[callback.from_user.id] = f"mod_{action}"
                await message.answer(
                    "Отправьте Telegram ID участника или ответьте на его сообщение.",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="✖️ Отмена", callback_data="input:cancel")
                    ]]),
                )
            return
        if action in {"summary", "chats"}:
            count = await database.registered_chat_count()
            body = owner_summary(owner_id, count) if action == "summary" else f"👥 Подключено групп: <b>{count}</b>"
            await message.answer(body, parse_mode="HTML", reply_markup=build_owner_keyboard())
        elif action == "myid":
            await message.answer(f"🆔 Ваш Telegram ID: <code>{owner_id}</code>", parse_mode="HTML", reply_markup=build_owner_keyboard())
        elif message.chat.type == "private":
            hints = {
                "settings": "Откройте эту панель в нужной группе, чтобы изменить настройки.",
                "modlog": "Откройте эту панель в нужной группе, чтобы посмотреть журнал.",
                "connect": "Добавьте бота в группу и выполните /connect от имени владельца.",
            }
            await message.answer(hints.get(action, "Это действие доступно в подключённой группе."), reply_markup=build_owner_keyboard())
        elif action == "settings":
            await show_group_settings(message.model_copy(update={"from_user": callback.from_user}), callback.bot, owner_id)
        elif action == "modlog":
            await show_moderation_log(message.model_copy(update={"from_user": callback.from_user}), callback.bot, owner_id)
        elif action == "connect":
            await register_group(message.model_copy(update={"from_user": callback.from_user}), callback.bot, owner_id)
        return

    if data == "input:cancel":
        PENDING_INPUTS.pop(callback.from_user.id, None)
        await message.answer("Ввод отменён.")


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


async def group_ban_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await ban_member(message, bot, owner_id)


async def group_unban_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await unban_member(message, bot, owner_id)


async def group_kick_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await kick_member(message, bot, owner_id)


async def group_purge_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await purge_messages(message, bot, owner_id)


async def group_warns_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_warnings(message, bot, owner_id)


async def group_clearwarns_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await clear_warnings(message, bot, owner_id)


async def group_modstats_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_moderation_stats(message, bot, owner_id)


async def button_input_handler(message: Message) -> None:
    """Consume requested forum lookup or moderation target input."""
    if not message.from_user or not message.text:
        return
    action = PENDING_INPUTS.pop(message.from_user.id, None)
    if not action:
        return
    if action in {"profile", "punish"}:
        synthetic = message.model_copy(update={"text": f"/{action} {message.text.strip()}"})
        await (cmd_profile if action == "profile" else cmd_punish)(synthetic)
        return
    if action in {"mod_warn", "mod_mute", "mod_unmute"}:
        synthetic = message.model_copy(update={"text": message.text.strip()})
        handlers = {
            "mod_warn": group_warn_handler,
            "mod_mute": group_mute_handler,
            "mod_unmute": group_unmute_handler,
        }
        await handlers[action](synthetic, message.bot)


async def advanced_reports_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await reports_command(message, bot, owner_id)


async def advanced_reportclose_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await reportclose_command(message, bot, owner_id)


async def advanced_blacklist_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await blacklist_command(message, bot, owner_id)


async def advanced_nickname_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await nickname_command(message, bot, owner_id)


async def advanced_role_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await role_command(message, bot, owner_id)


def create_dispatcher() -> Dispatcher:
    """Configure the moderation-first Telegram dispatcher."""
    dispatcher = Dispatcher()
    dispatcher.message.register(cmd_start, Command("start"))
    dispatcher.message.register(cmd_help, Command("help"))
    dispatcher.message.register(cmd_profile, Command("profile"))
    dispatcher.message.register(cmd_punish, Command("punish"))
    dispatcher.message.register(send_forum_stats, Command("stats"))
    dispatcher.message.register(cmd_owner, Command("owner"))
    dispatcher.message.register(cmd_myid, Command("myid"))
    dispatcher.message.register(cmd_chats, Command("chats"))
    dispatcher.message.register(group_register_handler, Command("connect"))
    dispatcher.message.register(group_settings_handler, Command("settings"))
    dispatcher.message.register(group_modlog_handler, Command("modlog"))
    dispatcher.message.register(group_warn_handler, Command("warn"))
    dispatcher.message.register(group_mute_handler, Command("mute"))
    dispatcher.message.register(group_unmute_handler, Command("unmute"))
    dispatcher.message.register(group_ban_handler, Command("ban"))
    dispatcher.message.register(group_unban_handler, Command("unban"))
    dispatcher.message.register(group_kick_handler, Command("kick"))
    dispatcher.message.register(group_purge_handler, Command("purge"))
    dispatcher.message.register(group_warns_handler, Command("warns"))
    dispatcher.message.register(group_clearwarns_handler, Command("clearwarns"))
    dispatcher.message.register(group_modstats_handler, Command("modstats"))
    dispatcher.message.register(report_command, Command("report"))
    dispatcher.message.register(advanced_reports_handler, Command("reports"))
    dispatcher.message.register(advanced_reportclose_handler, Command("reportclose"))
    dispatcher.message.register(advanced_blacklist_handler, Command("blacklist"))
    dispatcher.message.register(advanced_nickname_handler, Command("nick"))
    dispatcher.message.register(advanced_role_handler, Command("role"))
    dispatcher.message.register(button_input_handler, lambda message: bool(message.from_user and message.from_user.id in PENDING_INPUTS))
    dispatcher.message.register(group_moderation_handler)
    dispatcher.callback_query.register(cmd_menu_callback, F.data == "owner_panel")
    dispatcher.callback_query.register(cmd_menu_callback, F.data.startswith("menu:"))
    dispatcher.callback_query.register(cmd_menu_callback, F.data.startswith("owner:"))
    dispatcher.callback_query.register(cmd_menu_callback, F.data == "input:cancel")
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
        await bot.set_my_commands([
            BotCommand(command="start", description="Открыть главное меню"),
            BotCommand(command="help", description="Список команд"),
            BotCommand(command="profile", description="Профиль форума"),
            BotCommand(command="punish", description="Проверить наказание"),
            BotCommand(command="stats", description="Статистика форума"),
            BotCommand(command="connect", description="Подключить группу"),
            BotCommand(command="settings", description="Настройки модерации"),
            BotCommand(command="modlog", description="Журнал модерации"),
            BotCommand(command="modstats", description="Статистика модерации"),
            BotCommand(command="report", description="Отправить жалобу"),
            BotCommand(command="reports", description="Очередь жалоб"),
            BotCommand(command="reportclose", description="Закрыть жалобу"),
            BotCommand(command="blacklist", description="Общий чёрный список"),
            BotCommand(command="nick", description="Никнеймы группы"),
            BotCommand(command="role", description="Роли модерации"),
            BotCommand(command="warn", description="Выдать предупреждение"),
            BotCommand(command="warns", description="Проверить предупреждения"),
            BotCommand(command="clearwarns", description="Сбросить предупреждения"),
            BotCommand(command="mute", description="Ограничить на 10 минут"),
            BotCommand(command="unmute", description="Снять ограничение"),
            BotCommand(command="ban", description="Заблокировать участника"),
            BotCommand(command="unban", description="Снять блокировку"),
            BotCommand(command="kick", description="Исключить участника"),
            BotCommand(command="purge", description="Очистить сообщения"),
        ])
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
