"""Basic Telegram group moderation for F-rum-Bot.

The first release keeps counters in memory. Persistent storage and richer owner
controls are intentionally deferred until a durable database is configured.
"""
import re
import time
from collections import defaultdict, deque

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import ChatPermissions, Message

URL_RE = re.compile(r"(?:https?://|www\.|t\.me/|telegram\.me/)", re.IGNORECASE)
FLOOD_WINDOW_SECONDS = 8
FLOOD_MAX_MESSAGES = 6
WARNING_LIMIT = 3

_message_times: dict[tuple[int, int], deque[float]] = defaultdict(deque)
_warnings: dict[tuple[int, int], int] = defaultdict(int)
_registered_chats: set[int] = set()


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
    _registered_chats.add(message.chat.id)
    await message.answer(
        "✅ Эта группа подключена к F-rum-Bot.\n"
        "Режим: balanced.\n"
        "Ссылки от обычных участников блокируются; администраторам ссылки разрешены."
    )


async def moderate_message(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message) or not message.from_user or message.from_user.is_bot:
        return
    if message.from_user.id == owner_id:
        return
    if await is_chat_admin(bot, message.chat.id, message.from_user.id):
        return

    if contains_link(message):
        try:
            await message.delete()
            await message.answer(
                f"⚠️ {message.from_user.mention_html()}, ссылки в этой группе разрешены только администраторам.",
                parse_mode="HTML",
            )
        except Exception:
            # Missing delete permissions should not crash polling.
            return
        return

    key = (message.chat.id, message.from_user.id)
    now = time.monotonic()
    history = _message_times[key]
    while history and now - history[0] > FLOOD_WINDOW_SECONDS:
        history.popleft()
    history.append(now)
    if len(history) > FLOOD_MAX_MESSAGES:
        try:
            await message.delete()
            await message.answer(
                f"⏳ {message.from_user.mention_html()}, слишком много сообщений подряд. Сделай небольшую паузу.",
                parse_mode="HTML",
            )
        except Exception:
            return


async def warn_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
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
    key = (message.chat.id, target.id)
    _warnings[key] += 1
    count = _warnings[key]
    if count >= WARNING_LIMIT:
        try:
            await bot.restrict_chat_member(
                message.chat.id,
                target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=int(time.time()) + 300,
            )
            _warnings[key] = 0
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
        await message.answer(f"🔇 {target.mention_html()} ограничен на 10 минут.", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось применить ограничение. Проверь права бота.")


async def unmute_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
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
        await message.answer(f"🔊 Ограничение снято с {target.mention_html()}.", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось снять ограничение. Проверь права бота.")


def owner_summary(owner_id: int) -> str:
    return (
        "⚙️ <b>Панель владельца</b>\n\n"
        f"🆔 Ваш Telegram ID: <code>{owner_id}</code>\n"
        f"👥 Групп подключено в текущем запуске: <b>{len(_registered_chats)}</b>\n\n"
        "Команды:\n"
        "/myid — показать ваш ID\n"
        "/chats — показать число подключённых групп\n"
        "В группе: /warn, /mute, /unmute — ответом на сообщение."
    )


def registered_chat_count() -> int:
    return len(_registered_chats)
