"""Unified support tickets shared by the public website and Telegram bot."""
import hashlib
import hmac
import os
import time
from html import escape

from aiogram import F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from aiohttp import web

from database import database
from system_roles import has_permission

MAX_MESSAGE = 2000
WAITING_FOR_TICKET: set[int] = set()
WAITING_FOR_REPLY: dict[int, int] = {}


def _secret() -> bytes:
    value = os.getenv("PANEL_SESSION_SECRET", "").strip()
    if len(value) < 32:
        raise web.HTTPServiceUnavailable(text="Сервис поддержки временно не настроен.")
    return value.encode()


def _origin_allowed(request: web.Request) -> bool:
    origin = request.headers.get("Origin", "")
    allowed = {
        os.getenv("PANEL_ORIGIN", "").strip().rstrip("/"),
        os.getenv("PUBLIC_SITE_ORIGIN", "https://f-rum-bot-info.onrender.com").strip().rstrip("/"),
    }
    return bool(origin and origin.rstrip("/") in allowed)


def _cors(request: web.Request, response: web.StreamResponse) -> web.StreamResponse:
    origin = request.headers.get("Origin", "").rstrip("/")
    allowed = {
        os.getenv("PANEL_ORIGIN", "").strip().rstrip("/"),
        os.getenv("PUBLIC_SITE_ORIGIN", "https://f-rum-bot-info.onrender.com").strip().rstrip("/"),
    }
    if origin and origin in allowed:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


def _valid_telegram_login(data: dict) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    received = data.get("hash")
    if not token or not isinstance(received, str) or len(received) != 64:
        return False
    if any(isinstance(value, (dict, list)) for key, value in data.items() if key != "hash"):
        return False
    check = {key: value for key, value in data.items() if key != "hash"}
    payload = "\n".join(
        f"{key}={str(check[key]).lower() if isinstance(check[key], bool) else check[key]}"
        for key in sorted(check)
    )
    key = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return False
    try:
        user_id = int(data.get("id", 0))
        auth_date = int(data.get("auth_date", 0))
    except (TypeError, ValueError):
        return False
    return user_id > 0 and 0 <= int(time.time()) - auth_date <= 600


def _make_user_session(user_id: int) -> str:
    expires = int(time.time()) + 60 * 60 * 24 * 7
    payload = f"{user_id}.{expires}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _session_user(request: web.Request) -> int | None:
    token = request.cookies.get("support_session", "")
    try:
        user_text, expiry_text, signature = token.split(".", 2)
        payload = f"{user_text}.{expiry_text}"
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        user_id, expires = int(user_text), int(expiry_text)
        if user_id <= 0 or expires < int(time.time()) or not hmac.compare_digest(expected, signature):
            return None
        return user_id
    except (ValueError, web.HTTPException):
        return None


def _admin_session(request: web.Request) -> int | None:
    token = request.cookies.get("panel_session", "")
    try:
        user_text, expiry_text, signature = token.split(".", 2)
        payload = f"{user_text}.{expiry_text}"
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        user_id, expires = int(user_text), int(expiry_text)
        if user_id <= 0 or expires < int(time.time()) or not hmac.compare_digest(expected, signature):
            return None
        return user_id
    except (ValueError, web.HTTPException):
        return None


async def ensure_support_schema() -> None:
    pool = database._require_pool()
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL CHECK (char_length(subject) BETWEEN 1 AND 120),
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','waiting_user','waiting_support','closed')),
            assigned_to BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            closed_at TIMESTAMPTZ
        );
        CREATE INDEX IF NOT EXISTS support_tickets_status_updated_idx
            ON support_tickets(status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS support_tickets_user_idx
            ON support_tickets(user_id, updated_at DESC);
        CREATE TABLE IF NOT EXISTS support_messages (
            id BIGSERIAL PRIMARY KEY,
            ticket_id BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
            author_id BIGINT NOT NULL,
            author_role TEXT NOT NULL CHECK (author_role IN ('user','staff')),
            body TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS support_messages_ticket_idx
            ON support_messages(ticket_id, created_at, id);
    """)


async def support_options(request: web.Request) -> web.Response:
    response = web.Response(status=204)
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Max-Age"] = "600"
    return _cors(request, response)


async def support_login(request: web.Request) -> web.Response:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    try:
        data = await request.json()
    except (ValueError, web.HTTPBadRequest):
        raise web.HTTPBadRequest(text="Некорректные данные авторизации.")
    if not isinstance(data, dict) or not _valid_telegram_login(data):
        raise web.HTTPUnauthorized(text="Не удалось подтвердить вход через Telegram.")
    user_id = int(data["id"])
    response = web.json_response({"ok": True, "user": {
        "id": user_id, "first_name": str(data.get("first_name", ""))[:64],
        "username": str(data.get("username", ""))[:64],
        "photo_url": str(data.get("photo_url", ""))[:500],
    }})
    response.set_cookie("support_session", _make_user_session(user_id),
                        max_age=604800, httponly=True, secure=True,
                        samesite="None", path="/")
    return _cors(request, response)


async def support_me(request: web.Request) -> web.Response:
    user_id = _session_user(request)
    response = web.json_response({"authenticated": user_id is not None, "user_id": user_id})
    return _cors(request, response)


async def support_logout(request: web.Request) -> web.Response:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    response = web.json_response({"ok": True})
    response.del_cookie("support_session", path="/", secure=True, httponly=True, samesite="None")
    return _cors(request, response)


async def support_list(request: web.Request) -> web.Response:
    user_id = _session_user(request)
    if user_id is None:
        return _cors(request, web.json_response({"error": "Требуется вход через Telegram."}, status=401))
    pool = database._require_pool()
    rows = await pool.fetch(
        """SELECT t.id,t.subject,t.status,t.created_at,t.updated_at,
                  (SELECT body FROM support_messages m WHERE m.ticket_id=t.id ORDER BY m.id DESC LIMIT 1) last_message
           FROM support_tickets t WHERE t.user_id=$1 ORDER BY t.updated_at DESC LIMIT 50""", user_id)
    return _cors(request, web.json_response({"tickets": [
        {"id": r["id"], "subject": r["subject"], "status": r["status"],
         "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat(),
         "last_message": r["last_message"]} for r in rows]}))


async def support_create(request: web.Request) -> web.Response:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    user_id = _session_user(request)
    if user_id is None:
        return _cors(request, web.json_response({"error": "Требуется вход через Telegram."}, status=401))
    try:
        data = await request.json()
    except (ValueError, web.HTTPBadRequest):
        raise web.HTTPBadRequest(text="Некорректный запрос.")
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="Некорректный запрос.")
    subject = str(data.get("subject", "")).strip()[:120]
    body = str(data.get("message", "")).strip()[:MAX_MESSAGE]
    if not subject or not body:
        raise web.HTTPBadRequest(text="Укажите тему и сообщение.")
    pool = database._require_pool()
    recent = await pool.fetchval(
        "SELECT COUNT(*) FROM support_tickets WHERE user_id=$1 AND created_at >= NOW() - INTERVAL '1 hour'",
        user_id,
    )
    if int(recent or 0) >= 5:
        return _cors(request, web.json_response({"error": "Лимит новых обращений: не более 5 в час."}, status=429))
    async with pool.acquire() as conn:
        async with conn.transaction():
            ticket_id = await conn.fetchval(
                "INSERT INTO support_tickets(user_id,username,subject) VALUES($1,$2,$3) RETURNING id",
                user_id, str(data.get("username", ""))[:64], subject)
            await conn.execute(
                "INSERT INTO support_messages(ticket_id,author_id,author_role,body) VALUES($1,$2,'user',$3)",
                ticket_id, user_id, body)
    await _notify_support_staff(request.app["bot"], ticket_id, user_id, subject, body)
    return _cors(request, web.json_response({"ok": True, "ticket_id": ticket_id}, status=201))


async def support_thread(request: web.Request) -> web.Response:
    user_id = _session_user(request)
    if user_id is None:
        return _cors(request, web.json_response({"error": "Требуется вход через Telegram."}, status=401))
    ticket_id = int(request.match_info["ticket_id"])
    pool = database._require_pool()
    ticket = await pool.fetchrow(
        "SELECT id,user_id,subject,status,created_at,updated_at FROM support_tickets WHERE id=$1 AND user_id=$2",
        ticket_id, user_id)
    if not ticket:
        return _cors(request, web.json_response({"error": "Обращение не найдено."}, status=404))
    messages = await pool.fetch(
        "SELECT author_role,body,created_at FROM support_messages WHERE ticket_id=$1 ORDER BY id LIMIT 200",
        ticket_id)
    return _cors(request, web.json_response({
        "ticket": {"id": ticket["id"], "subject": ticket["subject"], "status": ticket["status"]},
        "messages": [{"author_role": m["author_role"], "body": m["body"], "created_at": m["created_at"].isoformat()} for m in messages]}))


async def support_reply(request: web.Request) -> web.Response:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    user_id = _session_user(request)
    if user_id is None:
        return _cors(request, web.json_response({"error": "Требуется вход через Telegram."}, status=401))
    ticket_id = int(request.match_info["ticket_id"])
    try:
        data = await request.json()
    except (ValueError, web.HTTPBadRequest):
        raise web.HTTPBadRequest(text="Некорректный запрос.")
    body = str(data.get("message", "")).strip()[:MAX_MESSAGE] if isinstance(data, dict) else ""
    if not body:
        raise web.HTTPBadRequest(text="Введите сообщение.")
    pool = database._require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ticket = await conn.fetchrow(
                "SELECT user_id,status FROM support_tickets WHERE id=$1 AND user_id=$2 FOR UPDATE",
                ticket_id, user_id)
            if not ticket or ticket["status"] == "closed":
                return _cors(request, web.json_response({"error": "Обращение закрыто или не найдено."}, status=404))
            recent = await conn.fetchval(
                "SELECT COUNT(*) FROM support_messages WHERE ticket_id=$1 AND author_id=$2 AND created_at >= NOW() - INTERVAL '1 minute'",
                ticket_id, user_id)
            if int(recent or 0) >= 8:
                return _cors(request, web.json_response({"error": "Слишком много сообщений за короткое время."}, status=429))
            await conn.execute(
                "INSERT INTO support_messages(ticket_id,author_id,author_role,body) VALUES($1,$2,'user',$3)",
                ticket_id, user_id, body)
            await conn.execute("UPDATE support_tickets SET status='waiting_support',updated_at=NOW() WHERE id=$1", ticket_id)
    await _notify_support_staff(request.app["bot"], ticket_id, user_id, "Ответ пользователя", body)
    return _cors(request, web.json_response({"ok": True}))


async def staff_ticket_queue(request: web.Request) -> web.Response:
    user_id = _admin_session(request)
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if user_id is None or not await has_permission(user_id, owner_id, "support"):
        return _cors(request, web.json_response({"error": "Недостаточно прав."}, status=403))
    pool = database._require_pool()
    rows = await pool.fetch(
        """SELECT t.id,t.user_id,t.username,t.subject,t.status,t.assigned_to,t.created_at,t.updated_at,
                  (SELECT body FROM support_messages m WHERE m.ticket_id=t.id ORDER BY m.id DESC LIMIT 1) last_message
           FROM support_tickets t ORDER BY CASE WHEN t.status='closed' THEN 1 ELSE 0 END,t.updated_at DESC LIMIT 100""")
    return _cors(request, web.json_response({"tickets": [
        {"id": r["id"], "user_id": r["user_id"], "username": r["username"], "subject": r["subject"],
         "status": r["status"], "assigned_to": r["assigned_to"],
         "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat(),
         "last_message": r["last_message"]} for r in rows]}))


async def staff_ticket_thread(request: web.Request) -> web.Response:
    user_id = _admin_session(request)
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if user_id is None or not await has_permission(user_id, owner_id, "support"):
        return _cors(request, web.json_response({"error": "Недостаточно прав."}, status=403))
    ticket_id = int(request.match_info["ticket_id"])
    pool = database._require_pool()
    ticket = await pool.fetchrow("SELECT id,user_id,username,subject,status,assigned_to FROM support_tickets WHERE id=$1", ticket_id)
    if not ticket:
        return _cors(request, web.json_response({"error": "Обращение не найдено."}, status=404))
    messages = await pool.fetch("SELECT author_id,author_role,body,created_at FROM support_messages WHERE ticket_id=$1 ORDER BY id LIMIT 200", ticket_id)
    return _cors(request, web.json_response({
        "ticket": {"id": ticket["id"], "user_id": ticket["user_id"], "username": ticket["username"],
                   "subject": ticket["subject"], "status": ticket["status"], "assigned_to": ticket["assigned_to"]},
        "messages": [{"author_id": m["author_id"], "author_role": m["author_role"], "body": m["body"],
                      "created_at": m["created_at"].isoformat()} for m in messages]}))


async def staff_ticket_reply(request: web.Request) -> web.Response:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    user_id = _admin_session(request)
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if user_id is None or not await has_permission(user_id, owner_id, "support"):
        return _cors(request, web.json_response({"error": "Недостаточно прав."}, status=403))
    ticket_id = int(request.match_info["ticket_id"])
    try:
        data = await request.json()
    except (ValueError, web.HTTPBadRequest):
        raise web.HTTPBadRequest(text="Некорректный запрос.")
    body = str(data.get("message", "")).strip()[:MAX_MESSAGE] if isinstance(data, dict) else ""
    if not body:
        raise web.HTTPBadRequest(text="Введите ответ.")
    pool = database._require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ticket = await conn.fetchrow("SELECT user_id,status FROM support_tickets WHERE id=$1 FOR UPDATE", ticket_id)
            if not ticket:
                return _cors(request, web.json_response({"error": "Обращение не найдено."}, status=404))
            if ticket["status"] == "closed":
                return _cors(request, web.json_response({"error": "Обращение закрыто."}, status=409))
            await conn.execute("INSERT INTO support_messages(ticket_id,author_id,author_role,body) VALUES($1,$2,'staff',$3)", ticket_id, user_id, body)
            await conn.execute("UPDATE support_tickets SET status='waiting_user',assigned_to=COALESCE(assigned_to,$2),updated_at=NOW() WHERE id=$1", ticket_id, user_id)
    try:
        await request.app["bot"].send_message(ticket["user_id"], f"💬 Ответ поддержки по обращению #{ticket_id}:\n\n{body}")
    except Exception:
        pass
    return _cors(request, web.json_response({"ok": True}))


async def staff_ticket_assign(request: web.Request) -> web.Response:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    user_id = _admin_session(request)
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if user_id is None or not await has_permission(user_id, owner_id, "support"):
        return _cors(request, web.json_response({"error": "Недостаточно прав."}, status=403))
    ticket_id = int(request.match_info["ticket_id"])
    row = await database._require_pool().fetchrow(
        "UPDATE support_tickets SET assigned_to=$2,updated_at=NOW() WHERE id=$1 AND status<>'closed' AND (assigned_to IS NULL OR assigned_to=$2) RETURNING id",
        ticket_id, user_id)
    if not row:
        return _cors(request, web.json_response({"error": "Обращение уже назначено другому сотруднику, закрыто или не найдено."}, status=409))
    return _cors(request, web.json_response({"ok": True, "assigned_to": user_id}))


async def staff_ticket_close(request: web.Request) -> web.Response:
    if not _origin_allowed(request):
        raise web.HTTPForbidden(text="Недопустимый источник запроса.")
    user_id = _admin_session(request)
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if user_id is None or not await has_permission(user_id, owner_id, "support"):
        return _cors(request, web.json_response({"error": "Недостаточно прав."}, status=403))
    ticket_id = int(request.match_info["ticket_id"])
    pool = database._require_pool()
    result = await pool.execute("UPDATE support_tickets SET status='closed',closed_at=NOW(),updated_at=NOW() WHERE id=$1 AND status<>'closed'", ticket_id)
    return _cors(request, web.json_response({"ok": result.endswith(" 1")}))


async def _notify_support_staff(bot, ticket_id: int, user_id: int, subject: str, body: str) -> None:
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    try:
        rows = await database.list_system_staff()
        recipients = {int(row["user_id"]) for row in rows if await has_permission(int(row["user_id"]), owner_id, "support")}
        if owner_id > 0:
            recipients.add(owner_id)
        message = f"📨 Новое сообщение в поддержке #{ticket_id}\nОт: {user_id}\nТема: {escape(subject[:120])}\n\n{escape(body[:1000])}\n\nОтвет: /supportreply {ticket_id} текст"
        for recipient in recipients:
            try:
                await bot.send_message(recipient, message, parse_mode="HTML")
            except Exception:
                continue
    except Exception:
        return


def support_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✉️ Создать обращение", callback_data="support:new")],
        [InlineKeyboardButton(text="📂 Мои обращения", callback_data="support:list")],
    ])


async def support_command(message: Message) -> None:
    if message.chat.type != "private" or not message.from_user:
        await message.reply("Откройте личный чат с ботом и используйте /support.")
        return
    await message.answer("🎧 <b>Поддержка F-rum-Bot</b>\nСоздайте обращение или посмотрите свои обращения.", reply_markup=support_keyboard(), parse_mode="HTML")


async def support_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    if callback.data == "support:new":
        WAITING_FOR_TICKET.add(user_id)
        await callback.message.answer("Напишите одним сообщением тему и описание проблемы. Например: «Не работает команда /stats — после запуска нет ответа».")
        await callback.answer("Ожидаю сообщение")
    elif callback.data == "support:list":
        rows = await database._require_pool().fetch(
            "SELECT id,subject,status FROM support_tickets WHERE user_id=$1 ORDER BY updated_at DESC LIMIT 10", user_id)
        if not rows:
            await callback.message.answer("У вас пока нет обращений.")
        else:
            labels = {"open": "Открыто", "waiting_user": "Ожидает вас", "waiting_support": "Ожидает поддержки", "closed": "Закрыто"}
            text = "\n".join(f"#{r['id']} · {escape(r['subject'])} · {labels.get(r['status'], r['status'])}" for r in rows)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"Ответить на #{r['id']}", callback_data=f"support:reply:{r['id']}")]
                for r in rows if r["status"] != "closed"
            ])
            await callback.message.answer(text + "\n\nВыберите обращение, чтобы ответить:", reply_markup=keyboard, parse_mode="HTML")
        await callback.answer()
    elif callback.data and callback.data.startswith("support:reply:"):
        raw_id = callback.data.rsplit(":", 1)[-1]
        if not raw_id.isdigit():
            await callback.answer("Некорректный номер обращения.", show_alert=True)
            return
        ticket_id = int(raw_id)
        ticket = await database._require_pool().fetchrow(
            "SELECT status FROM support_tickets WHERE id=$1 AND user_id=$2", ticket_id, user_id)
        if not ticket or ticket["status"] == "closed":
            await callback.answer("Обращение закрыто или не найдено.", show_alert=True)
            return
        WAITING_FOR_REPLY[user_id] = ticket_id
        await callback.message.answer(f"Напишите ответ для обращения #{ticket_id} одним сообщением.")
        await callback.answer("Ожидаю ответ")


async def support_private_message(message: Message) -> None:
    if not message.from_user or message.chat.type != "private" or not message.text:
        return
    user_id = message.from_user.id
    body = message.text.strip()[:MAX_MESSAGE]
    if user_id in WAITING_FOR_REPLY:
        ticket_id = WAITING_FOR_REPLY.pop(user_id)
        pool = database._require_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                ticket = await conn.fetchrow(
                    "SELECT status FROM support_tickets WHERE id=$1 AND user_id=$2 FOR UPDATE",
                    ticket_id, user_id)
                if not ticket or ticket["status"] == "closed":
                    await message.answer("Обращение закрыто или не найдено. Откройте /support.")
                    return
                recent = await conn.fetchval(
                    "SELECT COUNT(*) FROM support_messages WHERE ticket_id=$1 AND author_id=$2 AND created_at >= NOW() - INTERVAL '1 minute'",
                    ticket_id, user_id)
                if int(recent or 0) >= 8:
                    await message.answer("Слишком много сообщений за короткое время. Попробуйте позже.")
                    return
                await conn.execute(
                    "INSERT INTO support_messages(ticket_id,author_id,author_role,body) VALUES($1,$2,'user',$3)",
                    ticket_id, user_id, body)
                await conn.execute("UPDATE support_tickets SET status='waiting_support',updated_at=NOW() WHERE id=$1", ticket_id)
        await message.answer(f"Ответ добавлен в обращение #{ticket_id}.")
        await _notify_support_staff(message.bot, ticket_id, user_id, "Ответ пользователя", body)
        return
    if user_id not in WAITING_FOR_TICKET:
        return
    WAITING_FOR_TICKET.discard(user_id)
    if len(body) < 5:
        await message.answer("Сообщение слишком короткое. Нажмите /support и попробуйте ещё раз.")
        return
    recent = await database._require_pool().fetchval(
        "SELECT COUNT(*) FROM support_tickets WHERE user_id=$1 AND created_at >= NOW() - INTERVAL '1 hour'",
        user_id)
    if int(recent or 0) >= 5:
        await message.answer("Достигнут лимит новых обращений: не более 5 в час.")
        return
    pool = database._require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ticket_id = await conn.fetchval(
                "INSERT INTO support_tickets(user_id,username,subject) VALUES($1,$2,$3) RETURNING id",
                user_id, message.from_user.username or "", body[:120])
            await conn.execute("INSERT INTO support_messages(ticket_id,author_id,author_role,body) VALUES($1,$2,'user',$3)", ticket_id, user_id, body)
    await message.answer(f"✅ Обращение #{ticket_id} создано. Ответ придёт сюда и появится на сайте.")
    await _notify_support_staff(message.bot, ticket_id, user_id, body[:120], body)


async def support_queue_command(message: Message) -> None:
    if not message.from_user:
        return
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if not await has_permission(message.from_user.id, owner_id, "support"):
        await message.answer("⛔ Недостаточно прав.")
        return
    rows = await database._require_pool().fetch(
        "SELECT id,user_id,subject,status FROM support_tickets WHERE status<>'closed' ORDER BY updated_at DESC LIMIT 20")
    if not rows:
        await message.answer("📭 Активных обращений нет.")
        return
    await message.answer("\n".join(f"#{r['id']} · {r['user_id']} · {escape(r['subject'])} · {r['status']}\nОтвет: /supportreply {r['id']} текст" for r in rows), parse_mode="HTML")


async def support_reply_command(message: Message) -> None:
    if not message.from_user:
        return
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if not await has_permission(message.from_user.id, owner_id, "support"):
        await message.answer("⛔ Недостаточно прав.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].strip():
        await message.reply("Формат: /supportreply ID текст ответа")
        return
    ticket_id, body = int(parts[1]), parts[2][:MAX_MESSAGE]
    pool = database._require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            ticket = await conn.fetchrow("SELECT user_id,status FROM support_tickets WHERE id=$1 FOR UPDATE", ticket_id)
            if not ticket or ticket["status"] == "closed":
                await message.reply("Обращение не найдено или закрыто.")
                return
            await conn.execute("INSERT INTO support_messages(ticket_id,author_id,author_role,body) VALUES($1,$2,'staff',$3)", ticket_id, message.from_user.id, body)
            await conn.execute("UPDATE support_tickets SET status='waiting_user',assigned_to=$2,updated_at=NOW() WHERE id=$1", ticket_id, message.from_user.id)
    try:
        await message.bot.send_message(ticket["user_id"], f"💬 Ответ поддержки по обращению #{ticket_id}:\n\n{body}")
    except Exception:
        await message.answer("Ответ сохранён, но пользователь не запустил бота или недоступен для уведомлений.")
        return
    await message.answer(f"✅ Ответ отправлен по обращению #{ticket_id}.")


async def support_close_command(message: Message) -> None:
    if not message.from_user:
        return
    owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    if not await has_permission(message.from_user.id, owner_id, "support"):
        await message.answer("⛔ Недостаточно прав.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Формат: /supportclose ID")
        return
    result = await database._require_pool().execute(
        "UPDATE support_tickets SET status='closed',closed_at=NOW(),updated_at=NOW() WHERE id=$1 AND status<>'closed'",
        int(parts[1]))
    await message.answer("✅ Обращение закрыто." if result.endswith(" 1") else "Обращение не найдено или уже закрыто.")


def register_support_routes(app: web.Application) -> None:
    app.router.add_route("OPTIONS", "/api/support/{tail:.*}", support_options)
    app.router.add_post("/api/support/auth/telegram", support_login)
    app.router.add_get("/api/support/me", support_me)
    app.router.add_post("/api/support/logout", support_logout)
    app.router.add_get("/api/support/tickets", support_list)
    app.router.add_post("/api/support/tickets", support_create)
    app.router.add_get("/api/support/tickets/{ticket_id:[0-9]+}", support_thread)
    app.router.add_post("/api/support/tickets/{ticket_id:[0-9]+}/messages", support_reply)
    app.router.add_get("/api/support/staff/tickets", staff_ticket_queue)
    app.router.add_get("/api/support/staff/tickets/{ticket_id:[0-9]+}", staff_ticket_thread)
    app.router.add_post("/api/support/staff/tickets/{ticket_id:[0-9]+}/assign", staff_ticket_assign)
    app.router.add_post("/api/support/staff/tickets/{ticket_id:[0-9]+}/messages", staff_ticket_reply)
    app.router.add_post("/api/support/staff/tickets/{ticket_id:[0-9]+}/close", staff_ticket_close)


def register_support_bot(dispatcher) -> None:
    dispatcher.message.register(support_command, Command("support"))
    dispatcher.message.register(support_queue_command, Command("supportqueue"))
    dispatcher.message.register(support_reply_command, Command("supportreply"))
    dispatcher.message.register(support_close_command, Command("supportclose"))
    dispatcher.callback_query.register(support_callback, F.data.startswith("support:"))
    dispatcher.message.register(support_private_message, lambda message: bool(message.chat.type == "private" and message.from_user and message.text and (message.from_user.id in WAITING_FOR_TICKET or message.from_user.id in WAITING_FOR_REPLY)))
