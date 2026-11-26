"""Telegram bot for querying player information on a XenForo forum."""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from html import escape
from urllib.parse import parse_qsl, urljoin, urlsplit

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
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
from medical import manage_medical
from education import manage_education
from transport import manage_transport
from taxi import manage_taxi

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
    """Create the button-first main navigation keyboard."""
    rows = [
        [InlineKeyboardButton(text="🎮 Игра", callback_data="menu:game"), InlineKeyboardButton(text="💼 Работа", callback_data="menu:work")],
        [InlineKeyboardButton(text="🏛 Организации", callback_data="menu:organizations"), InlineKeyboardButton(text="💰 Экономика", callback_data="menu:economy")],
        [InlineKeyboardButton(text="🏙 Город", callback_data="menu:city"), InlineKeyboardButton(text="📋 Задания", callback_data="menu:quests")],
        [InlineKeyboardButton(text="🏆 Турниры", callback_data="menu:tournaments"), InlineKeyboardButton(text="🏢 Службы города", callback_data="menu:services")],
        [InlineKeyboardButton(text="👤 Профиль игрока", callback_data="menu:profile")],
        [InlineKeyboardButton(text="🛡 Проверить наказание", callback_data="menu:punish")],
    ]
    if is_owner:
        rows.append([InlineKeyboardButton(text="⚙️ Панель владельца", callback_data="owner_panel")])
    webapp_url = os.getenv("WEBAPP_URL", "https://f-rum-bot.onrender.com").strip()
    if webapp_url.startswith("https://"):
        rows.append([InlineKeyboardButton(text="📱 Открыть приложение", web_app=WebAppInfo(url=webapp_url))])
    rows.append([InlineKeyboardButton(text="🌐 Открыть форум", url=forum_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_section_keyboard(section: str) -> InlineKeyboardMarkup:
    """Build a submenu from supported button-driven features."""
    sections = {
        "game": [("👤 Игровой профиль", "view:game"), ("🎁 Ежедневная награда", "view:daily"), ("🏆 Рейтинг игроков", "view:top"), ("🎖 Достижения", "view:achievements")],
        "work": [("💼 Моя работа", "view:work"), ("📋 Список вакансий", "view:jobs")],
        "organizations": [("🏛 Список фракций", "view:factions"), ("⚔️ Управление фракцией", "input:faction"), ("👨‍👩‍👧 Семья", "input:family")],
        "economy": [("🛒 Магазин", "view:shop"), ("🎒 Инвентарь", "view:inventory"), ("🏠 Недвижимость", "view:property"), ("🚗 Гараж", "view:garage")],
        "city": [("📱 Телефон", "view:phone"), ("🗺 Карта города", "view:city"), ("📍 Места и организации", "view:places"), ("📅 События", "view:events"), ("📝 Запись на событие", "input:event")],
        "quests": [("📋 Задания", "view:quests"), ("⭐ Репутация", "view:reputation")],
        "tournaments": [("🏆 Турниры", "view:tournaments"), ("📝 Управление турниром", "input:tournament")],
        "services": [("🏛 Госслужба", "input:gov"), ("🚓 Служба", "input:service"), ("🏥 Медицина", "input:med"), ("🎓 Образование", "input:edu"), ("🚌 Транспорт", "input:bus"), ("🚕 Такси", "input:taxi")],
    }
    rows = [[InlineKeyboardButton(text=label, callback_data=data)] for label, data in sections.get(section, [])]
    rows.append([InlineKeyboardButton(text="⬅️ Главное меню", callback_data="menu:home")])
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


def validate_telegram_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram Mini App initData using Telegram's HMAC procedure."""
    if not init_data or len(init_data) > 8192 or not bot_token:
        return None
    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        received_hash = values.pop("hash", "")
        auth_date = int(values.get("auth_date", "0"))
        if not received_hash or abs(int(time.time()) - auth_date) > 86400:
            return None
        check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            return None
        user = json.loads(values.get("user", "{}"))
        if not isinstance(user, dict) or not isinstance(user.get("id"), int):
            return None
        return user
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


async def webapp_index(_request: web.Request) -> web.StreamResponse:
    """Serve the Telegram Mini App frontend."""
    page = Path(__file__).parent / "webapp" / "index.html"
    if not page.is_file():
        return web.Response(status=404, text="Mini App frontend not found")
    return web.FileResponse(page)


async def webapp_api(request: web.Request) -> web.Response:
    """Authenticated Mini App API for game data and safe player actions."""
    try:
        payload = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"error": "Некорректный запрос"}, status=400)
    user = validate_telegram_init_data(
        str(payload.get("init_data", "")),
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
    )
    if user is None:
        return web.json_response({"error": "Не удалось подтвердить Telegram. Откройте приложение из бота."}, status=401)
    user_id = user["id"]
    username = str(user.get("username") or user.get("first_name") or "Игрок")[:64]
    action = str(payload.get("action", "profile"))
    def rows(data):
        return [dict(item) for item in data]
    try:
        if action in {"profile", "me"}:
            profile = await database.get_game_profile(user_id, username)
            achievements = await database.sync_game_achievements(user_id)
            return web.json_response({"user": {"id": user_id, "first_name": user.get("first_name", ""), "username": user.get("username", "")},
                "profile": {"coins": profile["coins"], "xp": profile["xp"], "reputation": profile["reputation"], "daily_streak": profile["daily_streak"], "level": int(profile["xp"]) // 100 + 1},
                "achievements": len(achievements)})
        if action == "daily":
            profile, reward, claimed = await database.claim_game_daily(user_id, username)
            return web.json_response({"ok": claimed, "message": f"Получено: +{reward} монет и +50 XP." if claimed else "Ежедневная награда уже получена.", "profile": {"coins": profile["coins"], "xp": profile["xp"], "reputation": profile["reputation"], "daily_streak": profile["daily_streak"]}})
        if action == "shop":
            return web.json_response({"items": rows(await database.get_game_shop_items())})
        if action == "inventory":
            return web.json_response({"items": rows(await database.get_game_inventory(user_id))})
        if action == "property":
            owned = await database.get_game_property(user_id)
            return web.json_response({"owned": ({"id": owned["id"], "property_type": owned["property_type"], "name": owned["name"]} if owned else None), "items": rows(await database.get_game_property_catalog())})
        if action == "garage":
            return web.json_response({"owned": [{"id": v["id"], "name": v["name"], "description": v["description"]} for v in await database.get_game_vehicles(user_id)], "items": rows(await database.get_game_vehicle_catalog())})
        if action == "factions":
            current = await database.get_game_faction(user_id)
            return web.json_response({"items": rows(await database.get_game_factions()), "current": dict(current) if current else None})
        if action == "family":
            family = await database.get_game_family(user_id)
            members = await database.get_game_family_members(int(family["id"])) if family else []
            member_rows = [{"user_id": m["user_id"], "username": m["username"], "role": m["role"], "joined_at": m["joined_at"].isoformat()} for m in members]
            return web.json_response({"family": dict(family) if family else None, "members": member_rows})
        if action == "family_catalog":
            return web.json_response({"items": rows(await database.get_game_family_catalog())})
        if action == "faction_roster":
            faction, members = await database.get_game_faction_roster(user_id)
            return web.json_response({
                "faction": dict(faction) if faction else None,
                "members": [{"user_id": m["user_id"], "username": m["username"], "rank_name": m["rank_name"]} for m in members],
            })
        if action == "jobs":
            employment = await database.get_game_employment(user_id)
            return web.json_response({"items": rows(await database.get_game_jobs()), "employment": ({"job_id": employment["job_id"], "job_name": employment["job_name"], "description": employment["description"], "reward_coins": employment["reward_coins"], "rank_name": employment["rank_name"], "shifts_completed": employment["shifts_completed"], "last_shift_at": employment["last_shift_at"].isoformat() if employment["last_shift_at"] else None} if employment else None)})
        if action == "work_apply":
            try:
                job_id = int(payload.get("job_id", 0))
            except (TypeError, ValueError):
                job_id = 0
            ok, message = await database.apply_game_job(user_id, username, job_id)
            return web.json_response({"ok": ok, "message": message})
        if action == "work_shift":
            status, employment, reward = await database.perform_game_shift(user_id)
            messages = {"ok": f"Смена завершена. Начислено {reward} монет и 35 XP.", "no_job": "Сначала устройся на работу.", "cooldown": "Следующую смену можно выполнить через 10 минут."}
            return web.json_response({"ok": status == "ok", "status": status, "message": messages.get(status, "Не удалось выполнить смену.")})
        if action == "work_quit":
            ok = await database.quit_game_job(user_id)
            return web.json_response({"ok": ok, "message": "Ты уволился с работы." if ok else "У тебя нет работы."})
        if action == "leaderboard":
            return web.json_response({"items": rows(await database.get_game_leaderboard(10))})
        if action == "achievements":
            achievements = await database.sync_game_achievements(user_id)
            labels = {"first_steps": "Первые шаги", "experienced": "Опытный игрок", "wealthy": "Состоятельный житель", "reputation": "Уважаемый житель"}
            return web.json_response({"items": [{"code": a["achievement_code"], "title": labels.get(a["achievement_code"], a["achievement_code"]), "unlocked_at": a["unlocked_at"].isoformat()} for a in achievements]})
        if action == "quests":
            quests = await database.get_game_quests(user_id)
            return web.json_response({"items": [{"code": q["code"], "title": q["title"], "description": q["description"], "reward_coins": q["reward_coins"], "reward_xp": q["reward_xp"], "reward_reputation": q["reward_reputation"], "ready": q["ready"], "completed": q["completed_at"] is not None} for q in quests]})
        if action == "claim_quest":
            code = str(payload.get("code", ""))[:64]
            status, coins, xp, reputation = await database.claim_game_quest(user_id, username, code)
            messages = {"ok": f"Награда получена: +{coins} монет, +{xp} XP, +{reputation} репутации.", "not_ready": "Сначала выполни условие задания.", "claimed": "Это задание уже выполнено.", "missing": "Задание не найдено."}
            return web.json_response({"ok": status == "ok", "status": status, "message": messages.get(status, "Не удалось получить награду.")})
        if action == "reputation":
            player = await database.get_game_reputation(user_id)
            if player is None:
                return web.json_response({"player": None})
            score = int(player["reputation"])
            title = "Легенда города" if score >= 50 else "Уважаемый житель" if score >= 25 else "Известный житель" if score >= 10 else "Активный житель" if score >= 3 else "Новичок"
            return web.json_response({"player": {"username": player["username"], "xp": player["xp"], "coins": player["coins"], "reputation": score, "title": title}})
        if action in {"events", "join_event", "leave_event"}:
            events = [{"code": "fair", "title": "Городская ярмарка", "description": "Знакомство с городскими организациями и торговыми точками.", "starts_in_hours": 14}, {"code": "open_day", "title": "День открытых дверей", "description": "Презентации игровых фракций и профессий.", "starts_in_hours": 38}, {"code": "cleanup", "title": "Городской субботник", "description": "Совместное общественное мероприятие игроков.", "starts_in_hours": 62}]
            if action == "join_event":
                code = str(payload.get("code", ""))[:32]
                status = await database.signup_city_event(user_id, username, code)
                return web.json_response({"ok": status == "joined", "status": status, "message": {"joined": "Запись на событие подтверждена.", "already": "Ты уже записан на это событие.", "missing": "Неизвестное событие."}[status]})
            if action == "leave_event":
                code = str(payload.get("code", ""))[:32]
                status = await database.leave_city_event(user_id, code)
                return web.json_response({"ok": status == "left", "status": status, "message": {"left": "Запись отменена.", "not_joined": "Ты не записан на это событие.", "missing": "Неизвестное событие."}[status]})
            signed = {r["event_code"] for r in await database.get_user_city_event_signups(user_id)}
            return web.json_response({"items": [{**event, "joined": event["code"] in signed} for event in events]})
        if action == "tournaments":
            items = rows(await database.get_game_tournaments())
            return web.json_response({"items": items})
        if action == "join_tournament":
            try:
                tournament_id = int(payload.get("tournament_id", 0))
            except (TypeError, ValueError):
                tournament_id = 0
            status = await database.join_game_tournament(user_id, tournament_id)
            messages = {"joined": "Семья зарегистрирована на турнир.", "already": "Семья уже участвует.", "not_owner": "Записать семью может только её владелец.", "missing": "Турнир не найден.", "closed": "Регистрация закрыта."}
            return web.json_response({"ok": status == "joined", "status": status, "message": messages.get(status, "Не удалось записаться.")})
        if action == "transport":
            routes = rows(await database.list_transport_routes())
            return web.json_response({"routes": routes, "tickets": await database.get_transport_ticket_count(user_id), "history": [{"route": h["route_name"], "from": h["from_name"], "to": h["to_name"], "date": h["created_at"].isoformat()} for h in await database.get_transport_ride_history(user_id)]})
        if action == "transport_stops":
            try:
                route_id = int(payload.get("route_id", 0))
            except (TypeError, ValueError):
                route_id = 0
            stops = rows(await database.list_transport_stops(route_id))
            return web.json_response({"items": stops})
        if action == "buy_tickets":
            try:
                quantity = int(payload.get("quantity", 1))
            except (TypeError, ValueError):
                quantity = 0
            ok, message = await database.buy_transport_tickets(user_id, username, quantity)
            return web.json_response({"ok": ok, "message": message, "tickets": await database.get_transport_ticket_count(user_id)})
        if action == "ride_transport":
            try:
                route_id = int(payload.get("route_id", 0))
                from_stop = int(payload.get("from_stop_id", 0))
                to_stop = int(payload.get("to_stop_id", 0))
            except (TypeError, ValueError):
                return web.json_response({"error": "Некорректные остановки."}, status=400)
            ok, message = await database.ride_city_transport(user_id, route_id, from_stop, to_stop)
            return web.json_response({"ok": ok, "message": message, "tickets": await database.get_transport_ticket_count(user_id)})
        if action == "buy":
            kind, code = str(payload.get("kind", "")), str(payload.get("code", ""))
            if not code or len(code) > 64:
                return web.json_response({"error": "Некорректный товар."}, status=400)
            methods = {"item": database.buy_game_item, "property": database.buy_game_property, "vehicle": database.buy_game_vehicle}
            if kind not in methods:
                return web.json_response({"error": "Неизвестный тип покупки."}, status=400)
            status, price = await methods[kind](user_id, username, code)
            messages = {"ok": f"Покупка выполнена за {price} монет.", "funds": f"Недостаточно монет. Цена: {price}.", "owned": "У тебя уже есть недвижимость.", "limit": "Достигнут лимит транспорта.", "missing": "Товар больше недоступен."}
            return web.json_response({"ok": status == "ok", "message": messages.get(status, "Покупка не выполнена."), "status": status})
        if action == "join_faction":
            try:
                faction_id = int(payload.get("faction_id", 0))
            except (TypeError, ValueError):
                faction_id = 0
            ok, message = await database.join_game_faction(user_id, username, faction_id)
            return web.json_response({"ok": ok, "message": message})
        if action == "leave_faction":
            ok = await database.leave_game_faction(user_id)
            return web.json_response({"ok": ok, "message": "Ты покинул фракцию." if ok else "Ты не состоишь во фракции."})
        if action == "create_family":
            name = str(payload.get("name", "")).strip()
            if not 3 <= len(name) <= 32:
                return web.json_response({"error": "Название семьи должно содержать от 3 до 32 символов."}, status=400)
            ok, message = await database.create_game_family(user_id, username, name)
            return web.json_response({"ok": ok, "message": message})
        if action == "join_family":
            try:
                family_id = int(payload.get("family_id", 0))
            except (TypeError, ValueError):
                family_id = 0
            if family_id <= 0:
                return web.json_response({"error": "Укажи корректный ID семьи."}, status=400)
            ok, message = await database.join_game_family(user_id, family_id)
            return web.json_response({"ok": ok, "message": message})
        if action == "leave_family":
            ok, message = await database.leave_game_family(user_id)
            return web.json_response({"ok": ok, "message": message})
        return web.json_response({"error": "Неизвестное действие."}, status=400)
    except Exception:
        LOGGER.exception("Mini App API action failed: %s", action)
        return web.json_response({"error": "Не удалось выполнить действие. Попробуйте позже."}, status=500)


async def start_web_server(port: int) -> web.AppRunner:
    """Start the health server and Telegram Mini App routes."""
    app = web.Application(client_max_size=16 * 1024)
    app.router.add_get("/", webapp_index)
    app.router.add_get("/health", health_check)
    app.router.add_post("/api/webapp", webapp_api)
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
        "Выберите нужный раздел с помощью кнопок ниже.",
        parse_mode="HTML",
        reply_markup=build_main_keyboard(forum_url, is_owner=bool(message.from_user and message.from_user.id == int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0"))),
    )


async def cmd_menu_callback(callback: CallbackQuery) -> None:
    """Route navigation and owner controls through inline buttons."""
    data = callback.data or ""
    await callback.answer()
    message = callback.message
    if message is None:
        return
    PENDING_INPUTS.pop(callback.from_user.id, None)
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")

    if data == "owner_panel" or data.startswith("owner:"):
        if owner_id <= 0 or callback.from_user.id != owner_id:
            await message.answer("⛔ Панель доступна только владельцу бота.")
            return
        if data == "owner_panel":
            count = await database.registered_chat_count()
            await message.answer(owner_summary(owner_id, count), parse_mode="HTML", reply_markup=build_owner_keyboard())
            return
        action = data.split(":", 1)[1]
        if action in {"warn", "mute", "unmute"}:
            if message.chat.type == "private":
                await message.answer("Откройте меню владельца прямо в подключённой группе, затем выберите действие модерации.", reply_markup=build_owner_keyboard())
            else:
                PENDING_INPUTS[callback.from_user.id] = f"mod_{action}"
                await message.answer("Отправьте Telegram ID участника. Бот проверит права и выполнит действие.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data="input:cancel")]]))
            return
        if action in {"summary", "chats"}:
            count = await database.registered_chat_count()
            body = owner_summary(owner_id, count) if action == "summary" else f"👥 Подключено групп: <b>{count}</b>"
            await message.answer(body, parse_mode="HTML", reply_markup=build_owner_keyboard())
        elif action == "myid":
            await message.answer(f"🆔 Ваш Telegram ID: <code>{owner_id}</code>", parse_mode="HTML", reply_markup=build_owner_keyboard())
        elif message.chat.type == "private":
            hints = {
                "settings": "Откройте эту панель в нужной группе, чтобы изменить её настройки.",
                "modlog": "Откройте эту панель в нужной группе, чтобы посмотреть журнал модерации.",
                "connect": "Добавьте бота в нужную группу и нажмите «Подключить эту группу» прямо в ней.",
            }
            await message.answer(hints.get(action, "Это действие доступно внутри подключённой группы."), reply_markup=build_owner_keyboard())
        elif action == "settings":
            actor_message = message.model_copy(update={"from_user": callback.from_user})
            await show_group_settings(actor_message, callback.bot, owner_id)
        elif action == "modlog":
            actor_message = message.model_copy(update={"from_user": callback.from_user})
            await show_moderation_log(actor_message, callback.bot, owner_id)
        elif action == "connect":
            actor_message = message.model_copy(update={"from_user": callback.from_user})
            await register_group(actor_message, callback.bot, owner_id)
        return

    if data.startswith("input:"):
        action = data.split(":", 1)[1]
        prompts = {
            "faction": "Введите действие: info — информация; members — состав; claim — занять свободное лидерство; promote ID / demote ID — изменить ранг; kick ID — исключить; transfer ID — передать лидерство.",
            "family": "Введите одно из доступных действий: info — информация о семье; create НАЗВАНИЕ — создать семью; join ID — вступить по ID; leave — покинуть семью.",
            "tournament": "Введите действие (например: create Название 500, join ID, finish ID FAMILY_ID).",
            "gov": "Введите действие госслужбы (например: departments, profile, join ID, salary, tasks).",
            "service": "Введите действие службы (например: profile, apply МВД, tasks, leave).",
            "med": "Введите действие медицины (например: profile, centers, apply ID, tasks, leave).",
            "edu": "Введите действие образования (например: profile, institutions, groups, enroll ID).",
            "bus": "Введите действие транспорта (например: routes, tickets, ticket 1, history).",
            "taxi": "Введите действие такси (например: orders, order ROUTE FROM TO).",
            "event": "Введите действие события (например: mine, join fair, leave fair).",
        }
        if action == "cancel":
            await message.answer("Ввод отменён.")
        elif action in prompts:
            PENDING_INPUTS[callback.from_user.id] = action
            await message.answer(prompts[action], reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data="input:cancel")]]))
        return

    if data == "menu:home":
        await message.answer("Главное меню:", reply_markup=build_main_keyboard(get_forum_url(), is_owner=owner_id > 0 and callback.from_user.id == owner_id))
    elif data.startswith("menu:"):
        section = data.split(":", 1)[1]
        prompts = {
            "profile": "Для поиска профиля нажмите кнопку и затем отправьте ник игрока.",
            "punish": "Для проверки статуса нажмите кнопку и затем отправьте ник игрока.",
        }
        if section in prompts:
            PENDING_INPUTS[callback.from_user.id] = section
            await message.answer(prompts[section])
        else:
            await message.answer("Выберите действие:", reply_markup=build_section_keyboard(section))


async def cmd_view_callback(callback: CallbackQuery) -> None:
    """Open read-only screens from the button menus."""
    actions = {
        "game": show_game_profile, "daily": claim_daily_reward, "top": show_leaderboard,
        "achievements": show_achievements, "jobs": show_jobs, "work": show_work,
        "factions": show_factions, "shop": show_shop, "inventory": show_inventory,
        "property": show_properties, "garage": show_garage, "phone": show_phone,
        "city": show_city, "places": show_places, "events": show_events,
        "quests": show_quests, "reputation": show_reputation, "tournaments": show_tournaments,
    }
    await callback.answer()
    action = (callback.data or "").split(":", 1)[1]
    if callback.message and action in actions:
        actor_message = callback.message.model_copy(update={"from_user": callback.from_user})
        await actions[action](actor_message)


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


async def button_input_handler(message: Message) -> None:
    """Consume text input requested by a button and route it to the feature handler."""
    if not message.from_user or not message.text:
        return
    action = PENDING_INPUTS.pop(message.from_user.id, None)
    if not action:
        return
    if action in {"profile", "punish"}:
        synthetic_message = message.model_copy(update={"text": f"/{action} {message.text.strip()}"})
        await (cmd_profile if action == "profile" else cmd_punish)(synthetic_message)
        return
    from types import SimpleNamespace

    handlers = {
        "faction": manage_faction, "family": manage_family,
        "tournament": manage_tournament, "gov": manage_government,
        "service": manage_service, "med": manage_medical,
        "edu": manage_education, "bus": manage_transport,
        "taxi": manage_taxi, "event": manage_city_event,
    }
    if action in {"mod_warn", "mod_mute", "mod_unmute"}:
        moderation_handlers = {"mod_warn": group_warn_handler, "mod_mute": group_mute_handler, "mod_unmute": group_unmute_handler}
        await moderation_handlers[action](message, message.bot)
        return
    handler = handlers.get(action)
    if handler:
        await handler(message, SimpleNamespace(command=action, args=message.text.strip(), prefix="/", mention=None))


def create_dispatcher() -> Dispatcher:
    """Configure and return the Telegram dispatcher."""
    dispatcher = Dispatcher()
    # /start remains the technical entry point; all feature navigation uses buttons.
    dispatcher.message.register(cmd_start, Command("start"))
    dispatcher.message.register(button_input_handler, lambda message: bool(message.from_user and message.from_user.id in PENDING_INPUTS))
    dispatcher.message.register(group_moderation_handler)
    dispatcher.callback_query.register(cmd_menu_callback, F.data == "owner_panel")
    dispatcher.callback_query.register(cmd_menu_callback, F.data.startswith("menu:"))
    dispatcher.callback_query.register(cmd_menu_callback, F.data.startswith("owner:"))
    dispatcher.callback_query.register(cmd_menu_callback, F.data.startswith("input:"))
    dispatcher.callback_query.register(cmd_view_callback, F.data.startswith("view:"))
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
        await bot.delete_my_commands()
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
