"""Group information, administrators and rules commands."""
from html import escape

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import Message

from database import database
from moderation import is_chat_admin


async def _registered_group(message: Message) -> bool:
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.reply("Эта команда работает внутри группы.")
        return False
    if not await database.is_chat_registered(message.chat.id):
        await message.reply("Сначала подключите группу командой /connect от имени владельца.")
        return False
    return True


async def admins_command(message: Message, bot: Bot) -> None:
    if not await _registered_group(message):
        return
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
    except Exception:
        await message.reply("Не удалось получить список администраторов Telegram.")
        return
    lines = ["👮 <b>Администраторы группы</b>", ""]
    for member in admins:
        user = member.user
        if user.is_bot:
            continue
        name = escape(user.full_name)
        username = f" (@{escape(user.username)})" if user.username else ""
        role = "👑 Владелец" if member.status == "creator" else "🛡 Администратор"
        lines.append(f"• {role}: {name}{username} · <code>{user.id}</code>")
    if len(lines) == 2:
        lines.append("Администраторы не найдены.")
    await message.answer("\n".join(lines), parse_mode="HTML")


async def chatinfo_command(message: Message, bot: Bot) -> None:
    if not await _registered_group(message):
        return
    try:
        chat = await bot.get_chat(message.chat.id)
        member_count = await bot.get_chat_member_count(message.chat.id)
    except Exception:
        await message.reply("Не удалось получить информацию о группе через Telegram.")
        return
    settings = await database.get_chat_settings(message.chat.id)
    flood = {"off": "выключен", "balanced": "сбалансированный", "strict": "строгий"}.get(settings["moderation_mode"], "неизвестно")
    links = {"allow": "разрешены", "block": "удаляются", "mute": "удаляются с ограничением"}.get(settings["link_policy"], "неизвестно")
    lines = [
        "ℹ️ <b>Информация о группе</b>",
        f"Название: {escape(chat.title or 'Без названия')}",
        f"ID: <code>{chat.id}</code>",
        f"Тип: {'супергруппа' if chat.type == ChatType.SUPERGROUP else 'группа'}",
        f"Участников: <b>{member_count}</b>",
        "",
        "<b>Настройки модерации</b>",
        f"Антифлуд: {flood}",
        f"Ссылки: {links}",
    ]
    if chat.username:
        lines.insert(3, f"Публичная ссылка: @{escape(chat.username)}")
    await message.answer("\n".join(lines), parse_mode="HTML", disable_web_page_preview=True)


async def rules_command(message: Message) -> None:
    if not await _registered_group(message):
        return
    rules = await database.get_chat_rules(message.chat.id)
    if not rules:
        await message.answer("📜 Правила этой группы пока не установлены.")
        return
    await message.answer(f"📜 <b>Правила группы</b>\n\n{escape(rules)}", parse_mode="HTML")


async def setrules_command(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _registered_group(message):
        return
    actor = message.from_user
    if actor is None or not (actor.id == owner_id or await is_chat_admin(bot, message.chat.id, actor.id)):
        await message.reply("⛔ Устанавливать правила могут только администраторы группы.")
        return
    raw = (message.text or "").partition(" ")[2].strip()
    if not raw:
        await message.reply("Укажите текст правил: /setrules Уважайте участников...")
        return
    if len(raw) > 3500:
        await message.reply("Текст правил слишком длинный. Максимум — 3500 символов.")
        return
    await database.set_chat_rules(message.chat.id, raw)
    await message.answer("✅ Правила группы сохранены. Посмотреть их можно командой /rules.")
