"""Grand-style personal Telegram group statistics."""
from __future__ import annotations

from datetime import datetime
from html import escape

from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import Message

from database import database


class ChatActivityMiddleware(BaseMiddleware):
    """Persist visible group messages and join events for personal statistics."""

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}:
            if event.new_chat_members:
                inviter_id = event.from_user.id if event.from_user else None
                for member in event.new_chat_members:
                    if not member.is_bot:
                        await database.record_chat_member_join(
                            event.chat.id, member.id, member.username,
                            member.full_name, event.date, inviter_id,
                        )
            elif event.from_user and not event.from_user.is_bot:
                if event.text or event.caption or event.content_type not in {
                    "new_chat_members", "left_chat_member", "new_chat_title",
                    "new_chat_photo", "delete_chat_photo", "group_chat_created",
                    "supergroup_chat_created", "channel_chat_created",
                    "message_auto_delete_timer_changed", "migrate_to_chat_id",
                    "migrate_from_chat_id", "pinned_message",
                }:
                    await database.record_chat_message(
                        event.chat.id, event.from_user.id,
                        event.from_user.username, event.from_user.full_name,
                    )
        return await handler(event, data)


def _date(value) -> str:
    if not value:
        return "нет данных"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    return str(value)


def build_user_stats_message(user, stats, role_title: str, blocked: bool) -> str:
    nickname = stats.get("nickname") or user.full_name
    first_seen = _date(stats.get("first_seen_at"))
    date_label = "Дата вступления в чат" if stats.get("join_event_seen") else "Впервые замечен ботом"
    inviter_id = stats.get("invited_by")
    inviter = f"<code>{inviter_id}</code>" if inviter_id else "—"
    status = "🔒 да" if blocked else "нет"
    warnings = int(stats.get("warning_count") or 0)
    messages = int(stats.get("message_count") or 0)
    today = int(stats.get("today_count") or 0)
    rank = stats.get("activity_rank")
    rank_text = f"№{int(rank)}" if rank else "нет данных"
    username = f"@{escape(user.username)}" if user.username else "не указан"
    return (
        "🔎 <b>Информация о пользователе:</b>\n\n"
        f"🗣 Статус: ✨ {escape(role_title)}\n"
        f"⚠️ Предупреждений: {warnings}/3\n"
        f"📄 Никнейм: {escape(nickname)}\n"
        f"🚧 Блокировка чата: {status}\n"
        f"📅 {date_label}: {first_seen}\n\n"
        "📋 <b>Глобальная информация:</b>\n"
        "💎 VIP статус: нет данных\n"
        f"✍️ Сообщений отправлено: {messages}\n"
        f"📆 Сообщений сегодня: {today}\n"
        f"🏆 Место по активности: {rank_text}\n"
        f"👫 Пригласил(а): {inviter}\n"
        f"👤 Username: {username}\n"
        f"⚙️ ID: <code>{user.id}</code>"
    )


async def user_stats_command(message: Message) -> None:
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.answer("Команда /stats работает в подключённой группе.")
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключите группу командой /connect от имени владельца.")
        return

    target = message.reply_to_message.from_user if message.reply_to_message else None
    args = (message.text or "").split(maxsplit=1)
    if target is None and len(args) > 1:
        raw_id = args[1].strip()
        if not raw_id.isdecimal() or int(raw_id) <= 0:
            await message.reply("Укажите Telegram ID или ответьте на сообщение участника: /stats 123456.")
            return
        try:
            target = (await message.bot.get_chat_member(message.chat.id, int(raw_id))).user
        except Exception:
            await message.reply("Не удалось найти участника в этой группе. Проверьте ID.")
            return
    if target is None:
        target = message.from_user
    if target is None or target.is_bot:
        await message.reply("Не удалось определить пользователя.")
        return

    try:
        member = await message.bot.get_chat_member(message.chat.id, target.id)
    except Exception:
        await message.reply("Не удалось проверить участника через Telegram. Попробуйте позже.")
        return

    await database.ensure_chat_member_stats(message.chat.id, target.id, target.username, target.full_name)
    stats = await database.get_chat_member_stats(message.chat.id, target.id)
    priority = await database.get_chat_member_priority(message.chat.id, target.id)
    if member.status == "creator":
        role_title = "Владелец"
    elif member.status == "administrator":
        role_title = "Администратор"
    else:
        role_title = {80: "Главный администратор", 60: "Администратор", 40: "Модератор", 20: "Помощник"}.get(priority, "Пользователь")
        if priority not in {0, 20, 40, 60, 80}:
            role_title = await database.get_chat_member_role_title(message.chat.id, target.id) or "Пользователь"

    blocked = member.status == "kicked" or (
        member.status == "restricted" and not getattr(member, "can_send_messages", True)
    )
    await message.answer(
        build_user_stats_message(target, stats, role_title, blocked),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
