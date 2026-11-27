"""Per-chat role hierarchy, command thresholds and immunity for Telegram groups."""
from __future__ import annotations

import hashlib
import re
from html import escape

from aiogram.types import Message

from database import database

DEFAULT_COMMAND_PRIORITIES = {
    "warn": 20, "warns": 20, "clearwarns": 20,
    "mute": 20, "unmute": 20, "kick": 20,
    "ban": 40, "unban": 40, "purge": 40,
    "modstats": 20, "modlog": 20,
}
MANAGEABLE_COMMANDS = set(DEFAULT_COMMAND_PRIORITIES) | {
    "reports", "reportclose", "role", "nick", "blacklist",
}


def role_slug(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    if not normalized:
        normalized = hashlib.sha256(title.encode("utf-8")).hexdigest()[:10]
    return "custom_" + normalized[:20]


def can_manage_priority(actor_priority: int, target_priority: int) -> bool:
    return actor_priority > target_priority


async def effective_chat_priority(message: Message, owner_id: int) -> int:
    if not message.from_user:
        return 0
    user_id = message.from_user.id
    priority = await database.get_chat_member_priority(message.chat.id, user_id)
    if user_id == owner_id:
        return 100
    try:
        member = await message.bot.get_chat_member(message.chat.id, user_id)
        if member.status == "creator":
            priority = max(priority, 100)
        elif member.status == "administrator":
            priority = max(priority, 60)
    except Exception:
        pass
    from system_roles import get_role, has_permission, role_rank
    if await has_permission(user_id, owner_id, "moderation"):
        priority = max(priority, role_rank(await get_role(user_id, owner_id)))
    return priority


async def _group_and_actor(message: Message, bot, owner_id: int):
    if message.chat.type not in {"group", "supergroup"}:
        await message.reply("Эта команда работает только в группе.")
        return None
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключите группу командой /connect.")
        return None
    if not message.from_user:
        return None
    priority = await effective_chat_priority(message, owner_id)
    if priority < 80:
        await message.reply("⛔ Управлять ролями и порогами могут сотрудники с приоритетом 80+.")
        return None
    return priority


async def _resolve_role(chat_id: int, value: str):
    rows = await database.get_chat_role_definitions(chat_id)
    normalized = value.casefold()
    for row in rows:
        if row["role_key"].casefold() == normalized or row["title"].casefold() == normalized:
            return row
    return None


async def roles_command(message: Message, owner_id: int) -> None:
    if message.chat.type not in {"group", "supergroup"} or not await database.is_chat_registered(message.chat.id):
        await message.reply("Команда доступна в подключённой группе.")
        return
    rows = await database.get_chat_role_definitions(message.chat.id)
    lines = ["🎭 <b>Роли этой группы</b>", "👑 Владелец Telegram — 100", "👤 Обычный участник — 0"]
    lines.extend(f"• <b>{escape(row['title'])}</b> — {row['priority']} (<code>{escape(row['role_key'])}</code>)" for row in rows)
    await message.answer("\n".join(lines), parse_mode="HTML")


async def newrole_command(message: Message, owner_id: int) -> None:
    actor_priority = await _group_and_actor(message, message.bot, owner_id)
    if actor_priority is None:
        return
    raw = (message.text or "").partition(" ")[2].strip()
    parts = raw.rsplit(maxsplit=1)
    if len(parts) != 2:
        await message.reply("Формат: /newrole Название роли ПРИОРИТЕТ (1–79).")
        return
    title, raw_priority = parts
    try:
        priority = int(raw_priority)
    except ValueError:
        await message.reply("Приоритет должен быть числом от 1 до 79.")
        return
    if not 1 <= len(title) <= 32 or not 1 <= priority <= 79 or priority >= actor_priority:
        await message.reply("Название: 1–32 символа. Приоритет: 1–79 и строго ниже вашего.")
        return
    key = role_slug(title)
    created = await database.create_chat_role(
        message.chat.id, key, title, priority, message.from_user.id, actor_priority
    )
    await message.answer(
        f"✅ Роль <b>{escape(title)}</b> создана с приоритетом {priority}."
        if created else "Не удалось создать роль: такое имя или ключ уже существует.",
        parse_mode="HTML",
    )


async def delrole_command(message: Message, owner_id: int) -> None:
    actor_priority = await _group_and_actor(message, message.bot, owner_id)
    if actor_priority is None:
        return
    value = (message.text or "").partition(" ")[2].strip()
    role = await _resolve_role(message.chat.id, value) if value else None
    if not role:
        await message.reply("Формат: /delrole КЛЮЧ_ИЛИ_НАЗВАНИЕ. Системные роли удалить нельзя.")
        return
    deleted = await database.delete_chat_role(
        message.chat.id, role["role_key"], message.from_user.id, actor_priority
    )
    await message.answer(
        "✅ Роль удалена." if deleted
        else "Роль нельзя удалить: она системная, имеет равный/старший приоритет или ещё назначена участникам."
    )


async def set_chat_role_command(message: Message, owner_id: int) -> None:
    if message.chat.type not in {"group", "supergroup"} or not await database.is_chat_registered(message.chat.id):
        await message.reply("Команда доступна в подключённой группе.")
        return
    if not message.from_user:
        return
    actor_priority = await effective_chat_priority(message, owner_id)
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit():
        await message.reply("Формат: /chatrole TELEGRAM_ID КЛЮЧ_ИЛИ_НАЗВАНИЕ_РОЛИ.")
        return
    target_id = int(parts[1])
    if target_id == message.from_user.id:
        await message.reply("Нельзя назначить роль самому себе.")
        return
    try:
        target_member = await message.bot.get_chat_member(message.chat.id, target_id)
        if target_member.status in {"creator", "administrator"}:
            await message.reply("Роли бота не могут переопределять владельца и администраторов Telegram.")
            return
    except Exception:
        await message.reply("Не удалось проверить участника. Укажите ID существующего участника группы.")
        return
    role = await _resolve_role(message.chat.id, parts[2])
    if not role:
        await message.reply("Роль не найдена. Посмотрите список командой /roles.")
        return
    assigned = await database.assign_chat_role_guarded(
        message.chat.id, target_id, role["role_key"], message.from_user.id, actor_priority
    )
    await message.answer(
        f"✅ Роль <b>{escape(role['title'])}</b> назначена пользователю <code>{target_id}</code>."
        if assigned else "⛔ Назначение запрещено: нужен строго более высокий приоритет, цель не должна иметь иммунитет.",
        parse_mode="HTML",
    )


async def remove_chat_role_command(message: Message, owner_id: int) -> None:
    if message.chat.type not in {"group", "supergroup"} or not await database.is_chat_registered(message.chat.id):
        await message.reply("Команда доступна в подключённой группе.")
        return
    if not message.from_user:
        return
    actor_priority = await effective_chat_priority(message, owner_id)
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Формат: /removerole TELEGRAM_ID.")
        return
    removed = await database.remove_chat_role_guarded(
        message.chat.id, int(parts[1]), message.from_user.id, actor_priority
    )
    await message.answer("✅ Роль снята." if removed else "⛔ Нельзя снять роль равного/старшего сотрудника или роль отсутствует.")


async def editcmd_command(message: Message, owner_id: int) -> None:
    actor_priority = await _group_and_actor(message, message.bot, owner_id)
    if actor_priority is None:
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.reply("Формат: /editcmd КОМАНДА МИНИМАЛЬНЫЙ_ПРИОРИТЕТ.")
        return
    command = parts[1].lower().lstrip("/!")
    if command not in MANAGEABLE_COMMANDS or not parts[2].isdigit():
        await message.reply("Команда не поддерживается или приоритет указан неверно.")
        return
    minimum = int(parts[2])
    updated = await database.set_chat_command_priority(
        message.chat.id, command, minimum, message.from_user.id, actor_priority
    )
    await message.answer(
        f"✅ Для /{command} установлен минимальный приоритет {minimum}."
        if updated else "⛔ Минимальный приоритет должен быть от 0 до 100 и ниже вашего."
    )


async def gm_command(message: Message, owner_id: int) -> None:
    actor_priority = await _group_and_actor(message, message.bot, owner_id)
    if actor_priority is None:
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or parts[2].lower() not in {"on", "off"}:
        await message.reply("Формат: /gm TELEGRAM_ID on|off.")
        return
    target_id = int(parts[1])
    if target_id == message.from_user.id:
        await message.reply("Нельзя менять иммунитет самому себе.")
        return
    enabled = parts[2].lower() == "on"
    try:
        target_member = await message.bot.get_chat_member(message.chat.id, target_id)
        if target_member.status in {"creator", "administrator"}:
            await message.reply("Владельца и администраторов Telegram нельзя изменять через /gm.")
            return
    except Exception:
        await message.reply("Не удалось проверить участника группы.")
        return
    changed = await database.set_chat_immunity_guarded(
        message.chat.id, target_id, message.from_user.id, actor_priority, enabled
    )
    await message.answer(
        f"🛡 Иммунитет для <code>{target_id}</code> {'включён' if enabled else 'снят'}."
        if changed else "⛔ Нельзя менять иммунитет равному/старшему сотруднику."
    )


async def command_priority_allowed(message: Message, owner_id: int, command_name: str) -> bool:
    if not message.from_user:
        return False
    actor_priority = await effective_chat_priority(message, owner_id)
    configured_minimum = await database.get_chat_command_priority(message.chat.id, command_name)
    minimum = configured_minimum if configured_minimum is not None else DEFAULT_COMMAND_PRIORITIES.get(command_name, 0)
    if actor_priority < minimum:
        await message.reply(f"⛔ Для /{command_name} нужен приоритет не ниже {minimum}.")
        return False
    return True
