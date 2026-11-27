"""Community events and Telegram-native polls."""
import logging
import os
from datetime import datetime
from html import escape

from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database

LOGGER = logging.getLogger(__name__)


def parse_event_input(raw: str):
    """Parse: title | ISO-8601 datetime with timezone | description."""
    parts = [part.strip() for part in raw.split("|", 2)]
    if len(parts) != 3 or not all(parts):
        raise ValueError("Формат: название | 2026-12-01T18:00+03:00 | описание")
    try:
        starts_at = datetime.fromisoformat(parts[1])
    except ValueError as exc:
        raise ValueError("Неверная дата. Используй ISO-8601, например 2026-12-01T18:00+03:00") from exc
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise ValueError("Укажи часовой пояс, например +03:00")
    if len(parts[0]) > 100 or len(parts[2]) > 1000:
        raise ValueError("Название — до 100 символов, описание — до 1000.")
    return parts[0], starts_at, parts[2]


def parse_poll_input(raw: str):
    """Parse: question | option 1 | option 2 [| ...]."""
    parts = [part.strip() for part in raw.split("|")]
    if not 3 <= len(parts) <= 7 or not all(parts):
        raise ValueError("Формат: вопрос | вариант 1 | вариант 2 [| вариант 3 ...]")
    if len(parts[0]) > 200 or any(len(item) > 100 for item in parts[1:]):
        raise ValueError("Вопрос — до 200 символов, вариант — до 100.")
    if len({item.casefold() for item in parts[1:]}) != len(parts[1:]):
        raise ValueError("Варианты ответа не должны повторяться.")
    return parts[0], parts[1:]


async def ensure_events_schema() -> None:
    pool = database.pool
    if pool is None:
        raise RuntimeError("Database pool is not connected")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS community_events (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    created_by BIGINT NOT NULL,
                    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 100),
                    description TEXT NOT NULL DEFAULT '',
                    starts_at TIMESTAMPTZ NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','cancelled')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS community_events_chat_date_idx
                    ON community_events (chat_id, starts_at DESC);
                CREATE TABLE IF NOT EXISTS community_event_attendees (
                    event_id BIGINT NOT NULL REFERENCES community_events(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (event_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS community_polls (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    created_by BIGINT NOT NULL,
                    question TEXT NOT NULL CHECK (char_length(question) BETWEEN 1 AND 200),
                    options JSONB NOT NULL,
                    is_closed BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS community_poll_votes (
                    poll_id BIGINT NOT NULL REFERENCES community_polls(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    option_index INTEGER NOT NULL CHECK (option_index >= 0),
                    voted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (poll_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS community_polls_chat_created_idx
                    ON community_polls (chat_id, created_at DESC);
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
            await conn.execute("""
                INSERT INTO schema_migrations (version, description)
                VALUES ('0005_community_events_polls', 'Community events, registrations and polls')
                ON CONFLICT (version) DO NOTHING
            """)


def _owner(message: Message) -> bool:
    try:
        owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
    except ValueError:
        owner_id = 0
    return bool(message.from_user and owner_id > 0 and message.from_user.id == owner_id)


async def create_event_command(message: Message) -> None:
    if not _owner(message):
        await message.answer("⛔ Создавать мероприятия может только владелец проекта.")
        return
    raw = (message.text or "").partition(" ")[2].strip()
    try:
        title, starts_at, description = parse_event_input(raw)
    except ValueError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    async with database.pool.acquire() as conn:
        event_id = await conn.fetchval("""
            INSERT INTO community_events (chat_id, created_by, title, starts_at, description)
            VALUES ($1, $2, $3, $4, $5) RETURNING id
        """, message.chat.id, message.from_user.id, title, starts_at, description)
    await message.answer(
        f"📅 <b>Мероприятие создано</b>\n\n<b>{escape(title)}</b>\n"
        f"🕒 {starts_at.isoformat()}\n{escape(description)}\n\n"
        f"ID: <code>{event_id}</code>\nУчастники могут записаться через /events.",
        parse_mode="HTML",
    )


async def list_events_command(message: Message) -> None:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT e.id, e.title, e.description, e.starts_at,
                   COUNT(a.user_id)::int AS attendees
            FROM community_events e
            LEFT JOIN community_event_attendees a ON a.event_id=e.id
            WHERE e.chat_id=$1 AND e.status='open' AND e.starts_at > NOW() - INTERVAL '1 day'
            GROUP BY e.id ORDER BY e.starts_at LIMIT 10
        """, message.chat.id)
    if not rows:
        await message.answer("📅 Предстоящих мероприятий пока нет.")
        return
    for row in rows:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📝 Записаться", callback_data=f"event:join:{row['id']}"),
            InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"event:leave:{row['id']}"),
        ]])
        await message.answer(
            f"📅 <b>{escape(row['title'])}</b>\n{escape(row['description'])}\n"
            f"🕒 {row['starts_at'].isoformat()}\n👥 Записано: {row['attendees']}\n"
            f"ID: <code>{row['id']}</code>",
            reply_markup=keyboard, parse_mode="HTML",
        )


async def event_registration_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    try:
        action, raw_id = callback.data.rsplit(":", 1)
        event_id = int(raw_id)
    except (ValueError, TypeError):
        await callback.answer("Некорректное мероприятие.", show_alert=True)
        return
    async with database.pool.acquire() as conn:
        event = await conn.fetchrow(
            "SELECT id, chat_id, status, starts_at FROM community_events WHERE id=$1", event_id
        )
        if not event or event["status"] != "open" or event["starts_at"] <= datetime.now().astimezone():
            await callback.answer("Запись закрыта или мероприятие не найдено.", show_alert=True)
            return
        if action == "event:join":
            await conn.execute("""
                INSERT INTO community_event_attendees (event_id,user_id,display_name)
                VALUES ($1,$2,$3) ON CONFLICT (event_id,user_id)
                DO UPDATE SET display_name=EXCLUDED.display_name
            """, event_id, callback.from_user.id, callback.from_user.full_name[:100])
            text = "Вы записаны на мероприятие."
        else:
            await conn.execute(
                "DELETE FROM community_event_attendees WHERE event_id=$1 AND user_id=$2",
                event_id, callback.from_user.id,
            )
            text = "Запись отменена."
    await callback.answer(text)


async def create_poll_command(message: Message) -> None:
    if not _owner(message):
        await message.answer("⛔ Создавать голосования может только владелец проекта.")
        return
    try:
        question, options = parse_poll_input((message.text or "").partition(" ")[2].strip())
    except ValueError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    import json
    async with database.pool.acquire() as conn:
        poll_id = await conn.fetchval("""
            INSERT INTO community_polls (chat_id,created_by,question,options)
            VALUES ($1,$2,$3,$4::jsonb) RETURNING id
        """, message.chat.id, message.from_user.id, question, json.dumps(options, ensure_ascii=False))
    await message.answer(f"📊 Голосование #{poll_id}\n{escape(question)}")
    await show_poll(message, poll_id)


async def show_poll(message: Message, poll_id: int) -> None:
    async with database.pool.acquire() as conn:
        poll = await conn.fetchrow(
            "SELECT question, options, is_closed FROM community_polls WHERE id=$1 AND chat_id=$2",
            poll_id, message.chat.id,
        )
        if not poll:
            await message.answer("Голосование не найдено.")
            return
        options = poll["options"] if isinstance(poll["options"], list) else __import__("json").loads(poll["options"])
        counts = await conn.fetch("""
            SELECT option_index, COUNT(*)::int AS votes
            FROM community_poll_votes WHERE poll_id=$1 GROUP BY option_index
        """, poll_id)
    totals = {row["option_index"]: row["votes"] for row in counts}
    rows = []
    for index, option in enumerate(options):
        rows.append([InlineKeyboardButton(
            text=f"{option} · {totals.get(index, 0)}",
            callback_data=f"poll:vote:{poll_id}:{index}",
        )])
    if poll["is_closed"]:
        rows = []
    await message.answer(
        f"📊 <b>{escape(poll['question'])}</b>\n"
        + "\n".join(f"• {escape(option)} — {totals.get(i, 0)}" for i, option in enumerate(options))
        + ("\n\nГолосование закрыто." if poll["is_closed"] else "\n\nВыберите вариант:"),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None,
        parse_mode="HTML",
    )


async def list_polls_command(message: Message) -> None:
    async with database.pool.acquire() as conn:
        ids = await conn.fetch(
            "SELECT id FROM community_polls WHERE chat_id=$1 ORDER BY created_at DESC LIMIT 10",
            message.chat.id,
        )
    if not ids:
        await message.answer("📊 Голосований пока нет.")
        return
    for row in ids:
        await show_poll(message, row["id"])


async def poll_vote_callback(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        return
    try:
        _, _, raw_poll_id, raw_option = callback.data.split(":")
        poll_id, option_index = int(raw_poll_id), int(raw_option)
    except (ValueError, TypeError):
        await callback.answer("Некорректный вариант.", show_alert=True)
        return
    async with database.pool.acquire() as conn:
        async with conn.transaction():
            poll = await conn.fetchrow(
                "SELECT options,is_closed FROM community_polls WHERE id=$1", poll_id
            )
            if not poll or poll["is_closed"]:
                await callback.answer("Голосование закрыто.", show_alert=True)
                return
            options = poll["options"] if isinstance(poll["options"], list) else __import__("json").loads(poll["options"])
            if not 0 <= option_index < len(options):
                await callback.answer("Такого варианта нет.", show_alert=True)
                return
            await conn.execute("""
                INSERT INTO community_poll_votes (poll_id,user_id,option_index)
                VALUES ($1,$2,$3)
                ON CONFLICT (poll_id,user_id) DO UPDATE
                SET option_index=EXCLUDED.option_index,voted_at=NOW()
            """, poll_id, callback.from_user.id, option_index)
    await callback.answer("Голос учтён. Его можно изменить, выбрав другой вариант.")
    if callback.message:
        await show_poll(callback.message, poll_id)


def register_events_poll_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.message.register(create_event_command, Command("eventcreate"))
    dispatcher.message.register(list_events_command, Command("events"))
    dispatcher.message.register(create_poll_command, Command("pollcreate"))
    dispatcher.message.register(list_polls_command, Command("polls"))
    dispatcher.callback_query.register(event_registration_callback, F.data.startswith("event:"))
    dispatcher.callback_query.register(poll_vote_callback, F.data.startswith("poll:vote:"))
