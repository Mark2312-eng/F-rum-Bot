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
    authorized = message.from_user.id == owner_id
    if not authorized:
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            authorized = member.status in {"administrator", "creator"}
        except Exception:
            pass
    if not authorized:
        authorized = await database.get_chat_member_priority(message.chat.id, message.from_user.id) >= 20
    if not authorized:
        from system_roles import has_permission
        authorized = await has_permission(message.from_user.id, owner_id, "moderation")
    if not authorized:
        return False
    from chat_roles import command_priority_allowed
    command_name = (message.text or "").split(maxsplit=1)[0].split("@", 1)[0].lstrip("/!")
    return await command_priority_allowed(message, owner_id, command_name)


async def _can_manage_target(message: Message, bot: Bot, owner_id: int, target_id: int) -> bool:
    """Enforce per-chat priorities, global staff rank and immunity."""
    if not message.from_user:
        return False

    from chat_roles import effective_chat_priority, can_manage_priority
    from system_roles import get_role, role_rank

    actor_id = message.from_user.id
    actor_rank = await effective_chat_priority(message, owner_id)
    target_rank = await database.get_chat_member_priority(message.chat.id, target_id)
    target_rank = max(target_rank, role_rank(await get_role(target_id, owner_id)))
    try:
        target_member = await bot.get_chat_member(message.chat.id, target_id)
        if target_member.status == "creator":
            target_rank = max(target_rank, 100)
        elif target_member.status == "administrator":
            target_rank = max(target_rank, 60)
    except Exception:
        pass

    if await database.is_chat_member_immune(message.chat.id, target_id) and actor_rank < 100:
        await message.reply("🛡 Этот участник защищён иммунитетом /gm.")
        return False
    if not can_manage_priority(actor_rank, target_rank):
        await message.reply("⛔ Нельзя применять действия к пользователю с равным или более высоким приоритетом.")
        return False
    return True


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
    if await database.is_blacklisted(message.from_user.id):
        try:
            await message.delete()
            await bot.ban_chat_member(message.chat.id, message.from_user.id)
            await database.log_moderation_event(message.chat.id, None, message.from_user.id, "global_blacklist_ban")
        except Exception:
            return
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


async def _get_moderation_target(message: Message, bot: Bot):
    """Resolve a target from a replied-to message or a numeric Telegram ID."""
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    raw_text = (message.text or "").strip()
    raw_parts = raw_text.split(maxsplit=1)
    raw_id = raw_parts[1].split(maxsplit=1)[0].strip() if raw_text.startswith(("/", "!")) and len(raw_parts) > 1 else raw_text
    try:
        target_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    if target_id <= 0:
        return None
    try:
        member = await bot.get_chat_member(message.chat.id, target_id)
    except Exception:
        return None
    return member.user


async def warn_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключи эту группу кнопкой «Подключить эту группу» в панели владельца.")
        return
    if not await is_moderator(message, bot, owner_id):
        await message.reply("⛔ Команда доступна только владельцу и администраторам группы.")
        return
    target = await _get_moderation_target(message, bot)
    if target is None or target.is_bot:
        await message.reply("Ответьте на сообщение участника или укажите его Telegram ID.")
        return
    if target.id == owner_id or await is_chat_admin(bot, message.chat.id, target.id):
        await message.reply("Нельзя выдать предупреждение владельцу или администратору.")
        return
    if not await _can_manage_target(message, bot, owner_id, target.id):
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


MUTE_DURATIONS = {
    "5m": (300, "5 минут"),
    "10m": (600, "10 минут"),
    "30m": (1800, "30 минут"),
    "1h": (3600, "1 час"),
    "12h": (43200, "12 часов"),
    "1d": (86400, "1 день"),
    "7d": (604800, "7 дней"),
}


def parse_mute_duration(message: Message) -> tuple[int, str] | None:
    """Parse a safe, bounded mute duration from a command or reply."""
    args = (message.text or "").split()
    if message.reply_to_message:
        duration = args[1].lower() if len(args) > 1 else "10m"
    else:
        duration = args[2].lower() if len(args) > 2 else "10m"
    return MUTE_DURATIONS.get(duration)


async def mute_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not is_group(message):
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключи эту группу командой /connect от имени владельца бота.")
        return
    if not await is_moderator(message, bot, owner_id):
        await message.reply("⛔ Команда доступна только владельцу и администраторам группы.")
        return
    target = await _get_moderation_target(message, bot)
    if target is None or target.is_bot or target.id == owner_id:
        await message.reply("Ответь на сообщение участника или укажи его Telegram ID: /mute 123456 30m.")
        return
    if not await _can_manage_target(message, bot, owner_id, target.id):
        return
    if await is_chat_admin(bot, message.chat.id, target.id):
        await message.reply("Нельзя ограничить администратора группы.")
        return
    parsed_duration = parse_mute_duration(message)
    if parsed_duration is None:
        await message.reply("Срок: 5m, 10m, 30m, 1h, 12h, 1d или 7d. Пример: /mute 123456 30m.")
        return
    duration_seconds, duration_label = parsed_duration
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=int(time.time()) + duration_seconds,
        )
        await database.log_moderation_event(
            message.chat.id, message.from_user.id, target.id, "manual_mute", duration_label
        )
        await message.answer(f"🔇 {target.mention_html()} ограничен на {duration_label}.", parse_mode="HTML")
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
    target = await _get_moderation_target(message, bot)
    if target is None:
        await message.reply("Ответь на сообщение участника или укажи его Telegram ID: /unmute 123456.")
        return
    if not await _can_manage_target(message, bot, owner_id, target.id):
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


async def _moderation_command_allowed(message: Message, bot: Bot, owner_id: int) -> bool:
    if not is_group(message):
        await message.reply("Эта команда работает только в группе.")
        return False
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключите группу командой /connect от имени владельца.")
        return False
    if not await is_moderator(message, bot, owner_id):
        await message.reply("⛔ Для этой команды нужна роль помощника (20) или выше.")
        return False
    return True


async def ban_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _moderation_command_allowed(message, bot, owner_id):
        return
    target = await _get_moderation_target(message, bot)
    if target is None or target.is_bot or target.id == owner_id:
        await message.reply("Ответьте на сообщение участника или укажите ID: /ban 123456.")
        return
    if not await _can_manage_target(message, bot, owner_id, target.id):
        return
    if await is_chat_admin(bot, message.chat.id, target.id):
        await message.reply("Нельзя заблокировать администратора группы.")
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await database.log_moderation_event(message.chat.id, message.from_user.id, target.id, "ban")
        await message.answer(f"⛔ {target.mention_html()} заблокирован в группе.", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось заблокировать участника. Проверьте права бота.")


async def unban_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _moderation_command_allowed(message, bot, owner_id):
        return
    target = await _get_moderation_target(message, bot)
    if target is None:
        await message.reply("Укажите Telegram ID пользователя: /unban 123456.")
        return
    if not await _can_manage_target(message, bot, owner_id, target.id):
        return
    try:
        await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await database.log_moderation_event(message.chat.id, message.from_user.id, target.id, "unban")
        await message.answer(f"✅ Блокировка снята с пользователя <code>{target.id}</code>.", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось снять блокировку. Проверьте ID и права бота.")


async def kick_member(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _moderation_command_allowed(message, bot, owner_id):
        return
    target = await _get_moderation_target(message, bot)
    if target is None or target.is_bot or target.id == owner_id:
        await message.reply("Ответьте на сообщение участника или укажите ID: /kick 123456.")
        return
    if not await _can_manage_target(message, bot, owner_id, target.id):
        return
    if await is_chat_admin(bot, message.chat.id, target.id):
        await message.reply("Нельзя исключить администратора группы.")
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id, revoke_messages=False)
        await bot.unban_chat_member(message.chat.id, target.id, only_if_banned=True)
        await database.log_moderation_event(message.chat.id, message.from_user.id, target.id, "kick")
        await message.answer(f"👢 {target.mention_html()} исключён из группы. Он сможет вступить снова по ссылке.", parse_mode="HTML")
    except Exception:
        await message.reply("Не удалось исключить участника. Проверьте права бота.")


async def purge_messages(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _moderation_command_allowed(message, bot, owner_id):
        return
    args = (message.text or "").split(maxsplit=1)
    try:
        count = int(args[1]) if len(args) > 1 else 10
    except ValueError:
        count = 0
    if not 1 <= count <= 100:
        await message.reply("Укажите количество от 1 до 100: /purge 20.")
        return
    first_id = max(1, message.message_id - count + 1)
    message_ids = list(range(first_id, message.message_id + 1))
    try:
        deleted = await bot.delete_messages(message.chat.id, message_ids)
        await database.log_moderation_event(
            message.chat.id, message.from_user.id, None, "purge", f"диапазон до {message.message_id}, запрос {count}"
        )
        # Telegram's bulk delete endpoint does not return the exact deleted count.
        await message.answer(f"🧹 Запрос на очистку {count} последних сообщений выполнен.")
    except Exception:
        await message.reply("Не удалось очистить сообщения. Проверьте права бота и возраст сообщений.")


async def show_warnings(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _moderation_command_allowed(message, bot, owner_id):
        return
    target = await _get_moderation_target(message, bot)
    if target is None:
        await message.reply("Ответьте на сообщение участника или укажите ID: /warns 123456.")
        return
    count = await database.get_warning_count(message.chat.id, target.id)
    await message.answer(
        f"⚠️ У пользователя <code>{target.id}</code> предупреждений: <b>{count}/{WARNING_LIMIT}</b>.",
        parse_mode="HTML",
    )


async def clear_warnings(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _moderation_command_allowed(message, bot, owner_id):
        return
    target = await _get_moderation_target(message, bot)
    if target is None:
        await message.reply("Ответьте на сообщение участника или укажите ID: /clearwarns 123456.")
        return
    if not await _can_manage_target(message, bot, owner_id, target.id):
        return
    await database.reset_warnings(message.chat.id, target.id)
    await database.log_moderation_event(message.chat.id, message.from_user.id, target.id, "warnings_reset")
    await message.answer(f"✅ Предупреждения пользователя <code>{target.id}</code> сброшены.", parse_mode="HTML")


async def show_moderation_stats(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _moderation_command_allowed(message, bot, owner_id):
        return
    stats = await database.get_moderation_stats(message.chat.id)
    labels = {
        "warning": "Предупреждения", "auto_mute": "Автомуты", "manual_mute": "Муты",
        "unmute": "Снятие мута", "ban": "Блокировки", "unban": "Разблокировки",
        "kick": "Исключения", "purge": "Очистки", "link_deleted": "Удалённые ссылки",
        "link_mute": "Ограничения за ссылки", "flood_delete": "Антифлуд",
        "warnings_reset": "Сбросы предупреждений",
    }
    if not stats:
        await message.answer("📊 За последние 7 дней действий модерации не было.")
        return
    lines = ["📊 <b>Статистика модерации за 7 дней</b>", ""]
    lines.extend(f"• {labels.get(row['action'], row['action'])}: <b>{row['total']}</b>" for row in stats)
    await message.answer("\n".join(lines), parse_mode="HTML")


MODERATION_ACTION_LABELS = {
    "link_deleted": "Удалена ссылка",
    "link_mute": "Ограничение за ссылку",
    "flood_delete": "Удалено сообщение (антифлуд)",
    "warning": "Предупреждение",
    "auto_mute": "Автоматическое ограничение",
    "manual_mute": "Ручное ограничение",
    "unmute": "Снято ограничение",
    "ban": "Блокировка",
    "unban": "Разблокировка",
    "kick": "Исключение",
    "purge": "Очистка сообщений",
    "warnings_reset": "Сброс предупреждений",
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
        await message.answer("Журнал доступен внутри подключённой группы через панель владельца.")
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.answer("Сначала подключите группу кнопкой «Подключить эту группу» в панели владельца.")
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
        "Используйте кнопки ниже для сводки, списка групп и управления настройками. "
        "Настройки и журнал модерации открываются из меню, отправленного в нужной группе."
    )
