"""Telegram moderation bot for VISE RUSSIA XenForo community."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
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
from moderation import ban_member, clear_warnings, kick_member, moderate_message, mute_member, owner_summary, purge_messages, register_group, show_ban_info, show_ban_list, show_moderation_log, show_moderation_stats, show_warning_history, show_warning_list, show_warnings, unban_member, unmute_member, warn_member
from group_settings import apply_setting_callback, show_group_settings
from advanced_moderation import blacklist_command, nickname_command, report_command, reportclose_command, reports_command, role_command
from system_roles import staff_command, myrole_command, staffinfo_command, setrole_command, staffremove_command, stafflog_command, rolehelp_command, syshealth_command, reporthelp_command
from testing import create_test_command, add_question_command, send_test_command, test_results_command, handle_test_start, test_answer_callback
from chat_roles import roles_command, newrole_command, delrole_command, set_chat_role_command, remove_chat_role_command, editcmd_command, gm_command, rolelog_command, command_permissions_command
from user_stats import ChatActivityMiddleware, user_stats_command
from group_info import admins_command, chatinfo_command, rules_command, setrules_command

load_dotenv()

LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 10000
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=5, sock_read=10)
PENDING_INPUTS: dict[tuple[int, int], tuple[str, float]] = {}
PENDING_INPUT_TTL_SECONDS = 300


def set_pending_input(chat_id: int, user_id: int, action: str) -> None:
    """Store a one-time input request scoped to its chat and user."""
    now = time.monotonic()
    expired = [
        key for key, (_action, expires_at) in PENDING_INPUTS.items()
        if expires_at <= now
    ]
    for key in expired:
        PENDING_INPUTS.pop(key, None)
    PENDING_INPUTS[(chat_id, user_id)] = (
        action,
        now + PENDING_INPUT_TTL_SECONDS,
    )


def pop_pending_input(chat_id: int, user_id: int) -> str | None:
    """Consume a pending input once, rejecting expired or cross-chat state."""
    pending = PENDING_INPUTS.pop((chat_id, user_id), None)
    if pending is None:
        return None
    action, expires_at = pending
    return action if expires_at > time.monotonic() else None


def has_pending_input(chat_id: int, user_id: int) -> bool:
    """Check whether this user has an unexpired request in this chat."""
    pending = PENDING_INPUTS.get((chat_id, user_id))
    if pending is None:
        return False
    if pending[1] <= time.monotonic():
        PENDING_INPUTS.pop((chat_id, user_id), None)
        return False
    return True


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


def _panel_origin(request: web.Request) -> str:
    return os.getenv("PANEL_ORIGIN", "").strip().rstrip("/")


def _panel_cors(request: web.Request, response: web.StreamResponse) -> web.StreamResponse:
    origin = request.headers.get("Origin", "")
    allowed = _panel_origin(request)
    if allowed and origin == allowed:
        response.headers["Access-Control-Allow-Origin"] = allowed
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


def _panel_secret() -> bytes:
    secret = os.getenv("PANEL_SESSION_SECRET", "").strip()
    if len(secret) < 32:
        raise web.HTTPServiceUnavailable(text="Панель временно не настроена.")
    return secret.encode("utf-8")


def _telegram_login_valid(data: dict, bot_token: str) -> bool:
    received_hash = data.get("hash")
    if not isinstance(received_hash, str) or len(received_hash) != 64:
        return False
    check = {key: value for key, value in data.items() if key != "hash"}
    if not check or any(isinstance(value, (dict, list)) for value in check.values()):
        return False
    data_check = "\\n".join(f"{key}={check[key]}" for key in sorted(check))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected = hmac.new(secret_key, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return False
    try:
        auth_date = int(data.get("auth_date", "0"))
        user_id = int(data.get("id", "0"))
    except (TypeError, ValueError):
        return False
    return user_id > 0 and 0 <= int(time.time()) - auth_date <= 600


def _make_panel_session(user_id: int) -> str:
    expires = int(time.time()) + 3600
    payload = f"{user_id}.{expires}"
    signature = hmac.new(_panel_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _panel_user(request: web.Request) -> int | None:
    token = request.cookies.get("panel_session", "")
    try:
        user_text, expires_text, signature = token.split(".", 2)
        payload = f"{user_text}.{expires_text}"
        expected = hmac.new(_panel_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature) or int(expires_text) < int(time.time()):
            return None
        user_id = int(user_text)
    except (ValueError, UnicodeError, web.HTTPException):
        return None
    admin_id = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
    return user_id if admin_id.isdigit() and user_id == int(admin_id) else None


async def panel_options(request: web.Request) -> web.Response:
    response = web.Response(status=204)
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "600"
    return _panel_cors(request, response)


async def panel_config(request: web.Request) -> web.Response:
    response = web.json_response({"bot_username": os.getenv("PANEL_BOT_USERNAME", "").lstrip("@")})
    return _panel_cors(request, response)


async def panel_login(request: web.Request) -> web.Response:
    if request.headers.get("Origin", "") != _panel_origin(request) or not _panel_origin(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    try:
        data = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="Некорректные данные авторизации.")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="Некорректные данные авторизации.")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    admin_id = os.getenv("ADMIN_TELEGRAM_ID", "").strip()
    if not bot_token or not admin_id.isdigit() or not _telegram_login_valid(data, bot_token):
        raise web.HTTPUnauthorized(text="Не удалось подтвердить вход через Telegram.")
    if int(data.get("id", 0)) != int(admin_id):
        raise web.HTTPForbidden(text="Этот аккаунт не имеет доступа к панели.")
    response = web.json_response({"ok": True})
    response.set_cookie(
        "panel_session", _make_panel_session(int(admin_id)),
        max_age=3600, httponly=True, secure=True, samesite="None", path="/",
    )
    return _panel_cors(request, response)


async def panel_me(request: web.Request) -> web.Response:
    user_id = _panel_user(request)
    response = web.json_response({"authenticated": user_id is not None, "user_id": user_id})
    return _panel_cors(request, response)


async def panel_logout(request: web.Request) -> web.Response:
    response = web.json_response({"ok": True})
    response.del_cookie("panel_session", path="/", secure=True, httponly=True, samesite="None")
    return _panel_cors(request, response)


async def panel_dashboard(request: web.Request) -> web.Response:
    user_id = _panel_user(request)
    if user_id is None:
        response = web.json_response({"error": "Требуется авторизация."}, status=401)
        return _panel_cors(request, response)
    pool = database._require_pool()
    chats = await pool.fetch(
        "SELECT chat_id, title, moderation_mode, created_at FROM registered_chats ORDER BY title"
    )
    tests = await pool.fetch(
        """SELECT t.id, t.title, t.chat_id, t.role_key, t.pass_score, t.is_active,
                  t.created_at, COUNT(r.id) AS attempts,
                  COUNT(r.id) FILTER (WHERE r.passed) AS passed_count
           FROM moderation_tests t LEFT JOIN moderation_test_results r ON r.test_id = t.id
           GROUP BY t.id ORDER BY t.created_at DESC LIMIT 100"""
    )
    recent = await pool.fetch(
        """SELECT r.test_id, r.user_id, r.score_percent, r.passed, r.role_assigned, r.created_at,
                  t.title AS test_title
           FROM moderation_test_results r JOIN moderation_tests t ON t.id = r.test_id
           ORDER BY r.created_at DESC LIMIT 50"""
    )
    payload = {
        "chats": [{"chat_id": row["chat_id"], "title": row["title"],
                   "moderation_mode": row["moderation_mode"]} for row in chats],
        "tests": [{"id": row["id"], "title": row["title"], "chat_id": row["chat_id"],
                   "role_key": row["role_key"], "pass_score": row["pass_score"],
                   "is_active": row["is_active"], "attempts": row["attempts"],
                   "passed_count": row["passed_count"]} for row in tests],
        "results": [{"test_id": row["test_id"], "test_title": row["test_title"],
                     "user_id": row["user_id"], "score_percent": row["score_percent"],
                     "passed": row["passed"], "role_assigned": row["role_assigned"],
                     "created_at": row["created_at"].isoformat()} for row in recent],
    }
    response = web.json_response(payload)
    return _panel_cors(request, response)


async def start_web_server(port: int) -> web.AppRunner:
    """Start health-check and authenticated admin-panel API endpoints."""
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    app.router.add_route("OPTIONS", "/api/{tail:.*}", panel_options)
    app.router.add_get("/api/config", panel_config)
    app.router.add_post("/api/auth/telegram", panel_login)
    app.router.add_get("/api/me", panel_me)
    app.router.add_post("/api/logout", panel_logout)
    app.router.add_get("/api/dashboard", panel_dashboard)
    runner = web.AppRunner(app, access_log=LOGGER)
    await runner.setup()

    try:
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
    except BaseException:
        await runner.cleanup()
        raise

    LOGGER.info("Health-check and admin API server listening on 0.0.0.0:%s", port)
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


async def ping_command(message: Message) -> None:
    """Check bot responsiveness and PostgreSQL connectivity."""
    started = time.perf_counter()
    try:
        pool = database._require_pool()
        await pool.fetchval("SELECT 1")
    except Exception:
        LOGGER.exception("Ping database check failed")
        await message.answer("🏓 Бот отвечает.\n🗄 База данных: недоступна.")
        return
    elapsed_ms = (time.perf_counter() - started) * 1000
    await message.answer(
        "🏓 <b>Pong!</b> Бот работает.\n"
        "🗄 База данных: доступна.\n"
        f"⏱ Проверка БД: <b>{elapsed_ms:.0f} мс</b>",
        parse_mode="HTML",
    )


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
    if await handle_test_start(message):
        return
    try:
        forum_url = get_forum_url()
    except ValueError:
        LOGGER.exception("XF_URL configuration is invalid")
        await message.answer("⚠️ Сервис временно недоступен: неверно настроен адрес форума.")
        return

    await message.answer(
        "👋 <b>VISE RUSSIA — помощник сообщества</b>\n\n"
        "Единый центр инструментов для форума и Telegram-групп.\n\n"
        "<b>Что умеет бот</b>\n"
        "👤 Находит профили участников на XenForo\n"
        "🛡 Помогает команде модерировать подключённые группы\n"
        "📨 Принимает жалобы и ведёт журнал действий\n"
        "🎓 Поддерживает тестирование и систему локальных ролей\n\n"
        "<b>Начало работы</b>\n"
        "Добавьте бота в группу, выдайте необходимые права администратора, "
        "а затем подключите группу командой /connect от владельца бота.\n\n"
        "📖 Полный список возможностей: /help",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(forum_url, is_owner=bool(message.from_user and message.from_user.id == int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0"))),
    )


async def cmd_help(message: Message) -> None:
    """Show a structured guide to public, moderation, role and test commands."""
    await message.answer(
        "🛡 <b>F-rum-Bot — справочник команд</b>\n"
        "<i>Инструменты форума и модерации VISE RUSSIA</i>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "👤 <b>Форум</b>\n"
        "/profile НИК — открыть профиль участника\n"
        "/punish НИК — проверить статус наказания\n"
        "/stats — личная статистика участника группы\n"
        "/forumstats — статистика форума\n"
        "/ping — проверить работу бота\n\n"
        "🛡 <b>Модерация группы</b>\n"
        "/warn ID — выдать предупреждение\n"
        "/warns ID — посмотреть текущие предупреждения\n"
        "/warnhistory ID — история предупреждений\n"
        "/warnlist — список участников с предупреждениями\n"
        "/clearwarns ID — сбросить предупреждения\n"
        "/banlist — блокировки из журнала бота\n"
        "/baninfo ID — последнее действие блокировки\n"
        "/mute ID — ограничить на 10 минут\n"
        "/unmute ID — снять ограничение\n"
        "/ban ID · /unban ID — блокировка и разблокировка\n"
        "/kick ID — исключить участника\n"
        "/purge N — удалить последние 1–100 сообщений\n"
        "/modstats — статистика за 7 дней\n"
        "/modlog — журнал действий\n\n"
        "/admins — список администраторов группы\n"
        "/chatinfo — информация о группе\n"
        "/rules — правила группы\n"
        "/setrules ТЕКСТ — установить правила (для администраторов)\n"
        "/cmdperms — список прав команд\\n"
        "/editcmd КОМАНДА ПРИОРИТЕТ — изменить доступ\\n"
        "/roles — список ролей\\n"
        "/newrole НАЗВАНИЕ ПРИОРИТЕТ — создать роль\\n"
        "/chatrole ID РОЛЬ — назначить роль\\n"
        "/removerole ID — снять роль\\n"
        "/cmdperms — список порогов доступа к командам\\n"
        "⚙️ <b>Настройки и обращения</b>\n"
        "/settings — антифлуд и политика ссылок\n"
        "/report ПРИЧИНА — пожаловаться (ответом на сообщение)\n"
        "/reports — очередь жалоб\n"
        "/reportclose ID — закрыть жалобу\n"
        "/blacklist add ID ПРИЧИНА — добавить в общий список\n"
        "/blacklist del ID · /blacklist list — удалить или посмотреть\n"
        "/nick set ИМЯ — установить ник ответом на сообщение\n"
        "/nick ID — посмотреть ник участника\n\n"
        "👥 <b>Роли и права группы</b>\n"
        "/roles — список ролей и приоритетов\n"
        "/newrole НАЗВАНИЕ ПРИОРИТЕТ — создать роль (80+)\n"
        "/delrole КЛЮЧ — удалить неиспользуемую роль\n"
        "/chatrole ID КЛЮЧ — назначить роль\n"
        "/removerole ID — снять роль\n"
        "/editcmd КОМАНДА ПРИОРИТЕТ — настроить доступ (80+)\n"
        "/gm ID on|off — иммунитет участника (80+)\n"
        "/role add ID · /role del ID · /role list — управление модераторами\n\n"
        "🎓 <b>Тестирование и команда</b>\n"
        "/createtest — создать тест (системный приоритет 80+)\n"
        "/testadd — добавить вопрос\n"
        "/sendtest ID ТЕСТА — отправить приглашение\n"
        "/testresults ID — посмотреть результаты\n"
        "/myrole · /staff · /staffinfo ID — информация о команде\n"
        "/setrole ID КЛЮЧ · /staffremove ID — управление должностями\n"
        "/stafflog · /rolehelp — журнал и справка\n"
        "/syshealth — диагностика (технические роли)\n"
        "/reporthelp — регламент поддержки\n\n"
        "🔗 <b>Подключение</b>\n"
        "/connect — подключить текущую группу (только владелец бота)\n\n"
        "<i>Команды модерации работают в подключённых группах. "
        "Для действий с участниками бот должен иметь соответствующие права Telegram. "
        "Доступ к командам определяется ролью, приоритетом и настройками группы.</i>",
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
            set_pending_input(message.chat.id, callback.from_user.id, section)
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
                set_pending_input(message.chat.id, callback.from_user.id, f"mod_{action}")
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
        PENDING_INPUTS.pop((message.chat.id, callback.from_user.id), None)
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


async def group_warnhistory_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_warning_history(message, bot, owner_id)


async def group_warnlist_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_warning_list(message, bot, owner_id)


async def group_banlist_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_ban_list(message, bot, owner_id)


async def group_baninfo_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if owner_id > 0:
        await show_ban_info(message, bot, owner_id)


async def group_admins_handler(message: Message, bot: Bot) -> None:
    await admins_command(message, bot)


async def group_chatinfo_handler(message: Message, bot: Bot) -> None:
    await chatinfo_command(message, bot)


async def group_rules_handler(message: Message) -> None:
    await rules_command(message)


async def group_setrules_handler(message: Message, bot: Bot) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await setrules_command(message, bot, owner_id)


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
    action = pop_pending_input(message.chat.id, message.from_user.id)
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


async def system_staff_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await staff_command(message, owner_id)


async def system_myrole_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await myrole_command(message, owner_id)


async def system_staffinfo_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await staffinfo_command(message, owner_id)


async def system_setrole_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await setrole_command(message, owner_id)


async def system_staffremove_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await staffremove_command(message, owner_id)


async def system_stafflog_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await stafflog_command(message, owner_id)


async def system_rolehelp_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await rolehelp_command(message, owner_id)


async def system_syshealth_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await syshealth_command(message, owner_id)


async def system_reporthelp_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await reporthelp_command(message, owner_id)


async def test_create_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await create_test_command(message, owner_id)


async def test_add_question_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await add_question_command(message, owner_id)


async def test_send_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await send_test_command(message, owner_id)


async def test_results_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await test_results_command(message, owner_id)


async def chat_roles_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await roles_command(message, owner_id)


async def chat_newrole_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await newrole_command(message, owner_id)


async def chat_delrole_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await delrole_command(message, owner_id)


async def chat_setrole_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await set_chat_role_command(message, owner_id)


async def chat_removerole_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await remove_chat_role_command(message, owner_id)


async def chat_editcmd_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await editcmd_command(message, owner_id)


async def chat_cmdperms_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await command_permissions_command(message, owner_id)


async def chat_rolelog_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await rolelog_command(message, owner_id)


async def chat_gm_handler(message: Message) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    await gm_command(message, owner_id)


def create_dispatcher() -> Dispatcher:
    """Configure the moderation-first Telegram dispatcher."""
    dispatcher = Dispatcher()
    dispatcher.message.outer_middleware(ChatActivityMiddleware())
    dispatcher.message.register(cmd_start, Command("start"))
    dispatcher.message.register(cmd_help, Command("help"))
    dispatcher.message.register(cmd_profile, Command("profile"))
    dispatcher.message.register(cmd_punish, Command("punish"))
    dispatcher.message.register(user_stats_command, Command("stats"))
    dispatcher.message.register(send_forum_stats, Command("forumstats"))
    dispatcher.message.register(ping_command, lambda message: bool(message.text and message.text.split("@", 1)[0].strip().lower() == "/ping"))
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
    dispatcher.message.register(group_warnhistory_handler, Command("warnhistory"))
    dispatcher.message.register(group_warnlist_handler, Command("warnlist"))
    dispatcher.message.register(group_banlist_handler, Command("banlist"))
    dispatcher.message.register(group_baninfo_handler, Command("baninfo"))
    dispatcher.message.register(group_admins_handler, Command("admins"))
    dispatcher.message.register(group_chatinfo_handler, Command("chatinfo"))
    dispatcher.message.register(group_rules_handler, Command("rules"))
    dispatcher.message.register(group_setrules_handler, Command("setrules"))
    dispatcher.message.register(group_admins_handler, lambda message: bool(message.text and message.text.lower().strip() == "!admins"))
    dispatcher.message.register(group_chatinfo_handler, lambda message: bool(message.text and message.text.lower().strip() == "!chatinfo"))
    dispatcher.message.register(group_rules_handler, lambda message: bool(message.text and message.text.lower().strip() == "!rules"))
    dispatcher.message.register(group_setrules_handler, lambda message: bool(message.text and message.text.lower().startswith("!setrules ")))
    dispatcher.message.register(group_warnhistory_handler, lambda message: bool(message.text and message.text.lower().startswith("!warnhistory")))
    dispatcher.message.register(group_warnlist_handler, lambda message: bool(message.text and message.text.lower().strip() == "!warnlist"))
    dispatcher.message.register(group_banlist_handler, lambda message: bool(message.text and message.text.lower().strip() == "!banlist"))
    dispatcher.message.register(group_baninfo_handler, lambda message: bool(message.text and message.text.lower().startswith("!baninfo")))
    dispatcher.message.register(group_clearwarns_handler, Command("clearwarns"))
    dispatcher.message.register(group_modstats_handler, Command("modstats"))
    dispatcher.message.register(group_warn_handler, lambda message: bool(message.text and message.text.startswith("!warn ")))
    dispatcher.message.register(group_warns_handler, lambda message: bool(message.text and message.text.startswith("!warns ")))
    dispatcher.message.register(group_clearwarns_handler, lambda message: bool(message.text and message.text.startswith("!clearwarns ")))
    dispatcher.message.register(group_mute_handler, lambda message: bool(message.text and message.text.startswith("!mute ")))
    dispatcher.message.register(group_unmute_handler, lambda message: bool(message.text and message.text.startswith("!unmute ")))
    dispatcher.message.register(group_ban_handler, lambda message: bool(message.text and message.text.startswith("!ban ")))
    dispatcher.message.register(group_unban_handler, lambda message: bool(message.text and message.text.startswith("!unban ")))
    dispatcher.message.register(group_kick_handler, lambda message: bool(message.text and message.text.startswith("!kick ")))
    dispatcher.message.register(group_purge_handler, lambda message: bool(message.text and message.text.startswith("!purge ")))
    dispatcher.message.register(group_modstats_handler, lambda message: bool(message.text and message.text.startswith("!modstats ")))
    dispatcher.message.register(report_command, Command("report"))
    dispatcher.message.register(advanced_reports_handler, Command("reports"))
    dispatcher.message.register(advanced_reportclose_handler, Command("reportclose"))
    dispatcher.message.register(advanced_blacklist_handler, Command("blacklist"))
    dispatcher.message.register(advanced_nickname_handler, Command("nick"))
    dispatcher.message.register(advanced_role_handler, Command("role"))
    dispatcher.message.register(system_staff_handler, Command("staff"))
    dispatcher.message.register(system_myrole_handler, Command("myrole"))
    dispatcher.message.register(system_staffinfo_handler, Command("staffinfo"))
    dispatcher.message.register(system_setrole_handler, Command("setrole"))
    dispatcher.message.register(system_staffremove_handler, Command("staffremove"))
    dispatcher.message.register(system_stafflog_handler, Command("stafflog"))
    dispatcher.message.register(system_rolehelp_handler, Command("rolehelp"))
    dispatcher.message.register(system_syshealth_handler, Command("syshealth"))
    dispatcher.message.register(system_reporthelp_handler, Command("reporthelp"))
    dispatcher.message.register(test_create_handler, Command("createtest"))
    dispatcher.message.register(test_add_question_handler, Command("testadd"))
    dispatcher.message.register(test_send_handler, Command("sendtest"))
    dispatcher.message.register(test_results_handler, Command("testresults"))
    dispatcher.message.register(chat_roles_handler, Command("roles"))
    dispatcher.message.register(chat_newrole_handler, Command("newrole"))
    dispatcher.message.register(chat_delrole_handler, Command("delrole"))
    dispatcher.message.register(chat_setrole_handler, Command("chatrole"))
    dispatcher.message.register(chat_removerole_handler, Command("removerole"))
    dispatcher.message.register(chat_editcmd_handler, Command("editcmd"))
    dispatcher.message.register(chat_cmdperms_handler, Command("cmdperms"))
    dispatcher.message.register(chat_rolelog_handler, Command("rolelog"))
    dispatcher.message.register(chat_rolelog_handler, lambda message: bool(message.text and message.text.strip().lower() == "!rolelog"))
    dispatcher.message.register(chat_cmdperms_handler, Command("permissions"))
    dispatcher.message.register(chat_roles_handler, Command("rolelist"))
    dispatcher.message.register(chat_setrole_handler, Command("giverole"))
    dispatcher.message.register(chat_setrole_handler, Command("setrole"))
    dispatcher.message.register(chat_roles_handler, lambda message: bool(message.text and message.text.strip().lower() == "!rolelist"))
    dispatcher.message.register(chat_cmdperms_handler, lambda message: bool(message.text and message.text.strip().lower() == "!permissions"))
    dispatcher.message.register(chat_setrole_handler, lambda message: bool(message.text and message.text.startswith(("!giverole ", "!setrole "))))
    dispatcher.message.register(chat_cmdperms_handler, lambda message: bool(message.text and message.text.strip() == "!cmdperms"))
    dispatcher.message.register(chat_gm_handler, Command("gm"))
    dispatcher.message.register(chat_roles_handler, lambda message: bool(message.text and message.text.strip() == "!roles"))
    dispatcher.message.register(chat_newrole_handler, lambda message: bool(message.text and message.text.startswith("!newrole ")))
    dispatcher.message.register(chat_delrole_handler, lambda message: bool(message.text and message.text.startswith("!delrole ")))
    dispatcher.message.register(chat_setrole_handler, lambda message: bool(message.text and message.text.startswith("!setrole ")))
    dispatcher.message.register(chat_removerole_handler, lambda message: bool(message.text and message.text.startswith("!removerole ")))
    dispatcher.message.register(chat_editcmd_handler, lambda message: bool(message.text and message.text.startswith("!editcmd ")))
    dispatcher.message.register(chat_gm_handler, lambda message: bool(message.text and message.text.startswith("!gm ")))
    dispatcher.message.register(chat_setrole_handler, lambda message: bool(message.text and message.text.startswith("+role ")))
    dispatcher.message.register(chat_removerole_handler, lambda message: bool(message.text and message.text.startswith("-role ")))
    dispatcher.callback_query.register(test_answer_callback, F.data.startswith("testq:"))
    dispatcher.message.register(button_input_handler, lambda message: bool(message.from_user and has_pending_input(message.chat.id, message.from_user.id)))
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
            BotCommand(command="stats", description="Статистика участника группы"),
            BotCommand(command="forumstats", description="Статистика форума"),
            BotCommand(command="ping", description="Проверить работу бота"),
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
            BotCommand(command="myrole", description="Моя системная должность"),
            BotCommand(command="staff", description="Состав системной команды"),
            BotCommand(command="staffinfo", description="Карточка сотрудника"),
            BotCommand(command="setrole", description="Назначить системную должность"),
            BotCommand(command="staffremove", description="Снять системную должность"),
            BotCommand(command="stafflog", description="Журнал назначений"),
            BotCommand(command="rolehelp", description="Справка по должностям"),
            BotCommand(command="syshealth", description="Техническая диагностика"),
            BotCommand(command="reporthelp", description="Регламент поддержки"),
            BotCommand(command="createtest", description="Создать тест (системная команда 80+)"),
            BotCommand(command="testadd", description="Добавить вопрос в тест"),
            BotCommand(command="sendtest", description="Выдать тест пользователю"),
            BotCommand(command="testresults", description="Результаты теста"),
            BotCommand(command="roles", description="Роли этой группы"),
            BotCommand(command="newrole", description="Создать роль группы"),
            BotCommand(command="delrole", description="Удалить роль группы"),
            BotCommand(command="chatrole", description="Назначить роль участнику"),
            BotCommand(command="removerole", description="Снять роль участника"),
            BotCommand(command="editcmd", description="Изменить порог команды"),
            BotCommand(command="cmdperms", description="Показать права команд"),
            BotCommand(command="rolelog", description="История изменений ролей"),
            BotCommand(command="rolelist", description="Список ролей группы"),
            BotCommand(command="giverole", description="Назначить роль участнику"),
            BotCommand(command="cmdperms", description="Просмотр прав на команды"),
            BotCommand(command="gm", description="Управление иммунитетом"),
            BotCommand(command="warn", description="Выдать предупреждение"),
            BotCommand(command="warns", description="Проверить предупреждения"),
            BotCommand(command="warnhistory", description="История предупреждений"),
            BotCommand(command="warnlist", description="Список с предупреждениями"),
            BotCommand(command="banlist", description="Список блокировок из журнала"),
            BotCommand(command="baninfo", description="Информация о блокировке"),
            BotCommand(command="admins", description="Администраторы группы"),
            BotCommand(command="chatinfo", description="Информация о группе"),
            BotCommand(command="rules", description="Правила группы"),
            BotCommand(command="setrules", description="Установить правила группы"),
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
