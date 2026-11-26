"""Telegram group moderation backed by persistent PostgreSQL state."""
import re
import time
from collections import defaultdict, deque
from datetime import timezone
from html import escape

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import ChatPermissions, Message

from database import database

URL_RE = re.compile(r"(?:https?://|www\.|t\.me/|telegram\.me/)", re.IGNORECASE)
FLOOD_WINDOW_SECONDS = 8
FLOOD_MAX_MESSAGES = 6
FLOOD_LIMITS = {"off": None, "balanced": 6, "strict": 4}
LINK_POLICIES = {"allow", "block", "mute"}
WARNING_LIMIT = 3

_message_times: dict[tuple[int, int], deque[float]] = defaultdict(deque)


def is_group(message: Message) -> bool:
    return message.chat.type in {ChatType.GROUP, ChatType.SUPERGROUP}


def contains_link(message: Message) -> bool:
    if message.entities and any(
        entity.type in {"url", "text_link"}
        for entity in message.entities
    ):
        return True
    if message.caption_entities and any(
        entity.type in {"url", "text_link"}
        for entity in message.caption_entities
    ):
        return True
    return bool(URL_RE.search(message.text or message.caption or ""))


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in {"administrator", "creator"}


async def is_moderator(message: Message, bot: Bot, owner_id: int) -> bool:
    if not message.from_user:
        return False
    if message.from_user.id == owner_id:
        return True
    return await is_chat_admin(bot, message.chat.id, message.from_user.id)


async def register_group(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message) or not message.from_user:
        return
    if message.from_user.id != owner_id:
        return
    await database.register_chat(message.chat.id, message.chat.title or "", owner_id)
    await message.answer(
        "✅ Эта группа подключена к F-rum-Bot.\n"
        "Режим: balanced.\n"
        "Ссылки от обычных участников блокируются; администраторам ссылки разрешены."
    )


async def moderate_message(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message) or not message.from_user or message.from_user.is_bot:
        return
    if not await database.is_chat_registered(message.chat.id):
        return
    if message.from_user.id == owner_id:
        return
    if await is_chat_admin(bot, message.chat.id, message.from_user.id):
        return

    settings = await database.get_chat_settings(message.chat.id)
    if contains_link(message):
        policy = settings["link_policy"]
        if policy == "allow":
            return
        try:
            await message.delete()
            if policy == "mute":
                await bot.restrict_chat_member(
                    message.chat.id,
                    message.from_user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=int(time.time()) + 300,
                )
                await database.log_moderation_event(
                    message.chat.id, None, message.from_user.id, "link_mute", "5 минут"
                )
                await message.answer(
                    f"🔇 {message.from_user.mention_html()}, отправка ссылок запрещена. Ограничение на 5 минут.",
                    parse_mode="HTML",
                )
            else:
                await database.log_moderation_event(
                    message.chat.id, None, message.from_user.id, "link_deleted"
                )
                await message.answer(
                    f"⚠️ {message.from_user.mention_html()}, ссылки в этой группе разрешены только администраторам.",
                    parse_mode="HTML",
                )
        except Exception:
            # Missing delete/restrict permissions should not crash polling.
            return
        return

    flood_limit = FLOOD_LIMITS.get(settings["moderation_mode"], FLOOD_MAX_MESSAGES)
    if flood_limit is None:
        return

    key = (message.chat.id, message.from_user.id)
    now = time.monotonic()
    history = _message_times[key]
    while history and now - history[0] > FLOOD_WINDOW_SECONDS:
        history.popleft()
    history.append(now)
    if len(history) > flood_limit:
        try:
            await message.delete()
            await database.log_moderation_event(
                message.chat.id, None, message.from_user.id, "flood_delete"
            )
            await message.answer(
                f"⏳ {message.from_user.mention_html()}, слишком много сообщений подряд. Сделай небольшую паузу.",
                parse_mode="HTML",
            )
        except Exception:
            return


async def warn_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключи эту группу командой /connect от имени владельца бота.")
        return
    if not await is_moderator(message, bot, owner_id):
        await message.reply("⛔ Команда доступна только владельцу и администраторам группы.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target is None or target.is_bot:
        await message.reply("Ответь командой /warn на сообщение участника.")
        return
    if target.id == owner_id or await is_chat_admin(bot, message.chat.id, target.id):
        await message.reply("Нельзя выдать предупреждение владельцу или администратору.")
        return
    count = await database.add_warning(message.chat.id, target.id)
    await database.log_moderation_event(
        message.chat.id, message.from_user.id, target.id, "warning", f"{count}/{WARNING_LIMIT}"
    )
    if count >= WARNING_LIMIT:
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(time.time()) + 300,
            )
            await database.reset_warnings(message.chat.id, target.id)
            await database.log_moderation_event(
                message.chat.id, message.from_user.id, target.id, "auto_mute", "5 минут после 3 предупреждений"
            )
            await message.answer(
                f"🔇 {target.mention_html()} получил {WARNING_LIMIT} предупреждения и ограничен на 5 минут.",
                parse_mode="HTML",
            )
        except Exception:
            await message.reply("Не удалось применить ограничение. Проверь права бота.")
        return
    await message.answer(
        f"⚠️ {target.mention_html()}, предупреждение {count}/{WARNING_LIMIT}.",
        parse_mode="HTML",
    )


async def mute_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключи эту группу командой /connect от имени владельца бота.")
        return
    if not await is_moderator(message, bot, owner_id):
        await message.reply("⛔ Команда доступна только владельцу и администраторам группы.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target is None or target.is_bot or target.id == owner_id:
        await message.reply("Ответь командой /mute на сообщение участника.")
        return
    if await is_chat_admin(bot, message.chat.id, target.id):
        await message.reply("Нельзя ограничить администратора группы.")
        return
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=int(time.time()) + 600,
        )
        await database.log_moderation_event(
            message.chat.id, message.from_user.id, target.id, "manual_mute", "10 минут"
        )
        await message.answer(f"🔇 {target.mention_html()} ограничен на 10 минут.", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось применить ограничение. Проверь права бота.")


async def unmute_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключи эту группу командой /connect от имени владельца бота.")
        return
    if not await is_moderator(message, bot, owner_id):
        await message.reply("⛔ Команда доступна только владельцу и администраторам группы.")
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if target is None:
        await message.reply("Ответь командой /unmute на сообщение участника.")
        return
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await database.log_moderation_event(
            message.chat.id, message.from_user.id, target.id, "unmute"
        )
        await message.answer(f"🔊 Ограничение снято с {target.mention_html()}.", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось снять ограничение. Проверь права бота.")


MODERATION_ACTION_LABELS = {
    "link_deleted": "Удалена ссылка",
    "link_mute": "Ограничение за ссылку",
    "flood_delete": "Удалено сообщение (антифлуд)",
    "warning": "Предупреждение",
    "auto_mute": "Автоматическое ограничение",
    "manual_mute": "Ручное ограничение",
    "unmute": "Снято ограничение",
}


def format_moderation_log(events: list) -> str:
    if not events:
        return "📋 <b>Журнал модерации</b>\n\nСобытий пока нет."
    lines = ["📋 <b>Последние события модерации</b>", ""]
    for event in events:
        action = MODERATION_ACTION_LABELS.get(event["action"], "Действие модерации")
        target_id = event["target_id"]
        actor_id = event["actor_id"]
        timestamp = event["created_at"]
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        time_text = timestamp.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
        details = f" · {escape(str(event['details']))}" if event["details"] else ""
        actor_text = f" · модератор <code>{actor_id}</code>" if actor_id else ""
        lines.append(
            f"• <b>{action}</b> — <code>{target_id if target_id is not None else '—'}</code>"
            f"{details}{actor_text}\n  <i>{time_text}</i>"
        )
    return "\n".join(lines)


async def show_moderation_log(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
        await message.answer("Команда /modlog доступна внутри подключённой группы.")
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.answer("Сначала подключите группу командой /connect от имени владельца бота.")
        return
    if not await is_moderator(message, bot, owner_id):
        await message.answer("⛔ Журнал доступен только владельцу бота и администраторам группы.")
        return
    events = await database.get_recent_moderation_events(message.chat.id, 10)
    await message.answer(format_moderation_log(events), parse_mode="HTML")


def owner_summary(owner_id: int, chat_count: int) -> str:
    return (
        "⚙️ <b>Панель владельца</b>\n\n"
        f"🆔 Ваш Telegram ID: <code>{owner_id}</code>\n"
        f"👥 Подключено групп: <b>{chat_count}</b>\n\n"
        "Команды:\n"
        "/myid — показать ваш ID\n"
        "/chats — показать число подключённых групп\n"
        "В группе: /connect, /settings, /modlog, /warn, /mute, /unmute — ответом на сообщение."
    )
