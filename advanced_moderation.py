"""Extended community tools: reports, global blacklist, nicknames and delegated moderators."""
from html import escape

from aiogram import Bot
from aiogram.types import Message

from database import database


async def _allowed(message: Message, bot: Bot, owner_id: int) -> bool:
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer("Эта команда работает в группе.")
        return False
    if not await database.is_chat_registered(message.chat.id):
        await message.answer("Сначала подключите группу командой /connect.")
        return False
    if not message.from_user:
        return False
    if message.from_user.id == owner_id:
        return True
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status in {"administrator", "creator"}:
        return True
    if await database.is_custom_moderator(message.chat.id, message.from_user.id):
        return True
    from system_roles import has_permission
    import os
    configured_owner = int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    return await has_permission(message.from_user.id, configured_owner, "reports")


async def report_command(message: Message, bot: Bot) -> None:
    if message.chat.type not in {"group", "supergroup"} or not await database.is_chat_registered(message.chat.id):
        await message.reply("Жалобы доступны в подключённых группах.")
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("Ответьте на сообщение и укажите причину: /report причина.")
        return
    if not message.from_user:
        return
    reason = (message.text or "").partition(" ")[2].strip()[:500]
    if not reason:
        await message.reply("Укажите причину жалобы: /report спам.")
        return
    target = message.reply_to_message.from_user
    if target.id == message.from_user.id or target.is_bot:
        await message.reply("Нельзя отправить жалобу на себя или бота.")
        return
    report_id = await database.create_report(message.chat.id, message.from_user.id, target.id, reason)
    await message.reply(f"✅ Жалоба #{report_id} передана модераторам.")


async def reports_command(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _allowed(message, bot, owner_id):
        return
    rows = await database.get_open_reports(message.chat.id)
    if not rows:
        await message.answer("📭 Открытых жалоб нет.")
        return
    lines = ["📨 <b>Открытые жалобы</b>", ""]
    for row in rows:
        lines.append(
            f"#{row['id']} · пользователь <code>{row['target_id']}</code>\n"
            f"От <code>{row['reporter_id']}</code>: {escape(row['reason'])}"
        )
    await message.answer("\n\n".join(lines), parse_mode="HTML")


async def reportclose_command(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _allowed(message, bot, owner_id):
        return
    from moderation import is_moderator
    if not await is_moderator(message, bot, owner_id):
        await message.reply("⛔ Закрывать жалобы могут модераторы и руководство.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Формат: /reportclose ID_ЖАЛОБЫ.")
        return
    closed = await database.close_report(message.chat.id, int(parts[1]), message.from_user.id)
    await message.answer("✅ Жалоба закрыта." if closed else "Жалоба не найдена или уже закрыта.")


async def blacklist_command(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _allowed(message, bot, owner_id):
        return
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if message.from_user.id != owner_id and member.status not in {"administrator", "creator"}:
        await message.reply("⛔ Общий чёрный список доступен только владельцу и администраторам Telegram.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2:
        await message.reply("Формат: /blacklist add ID причина | /blacklist del ID | /blacklist list.")
        return
    action = parts[1].lower()
    if action == "list":
        rows = await database.get_blacklist()
        if not rows:
            await message.answer("Чёрный список пуст.")
            return
        await message.answer("⛔ <b>Глобальный чёрный список</b>\n" + "\n".join(
            f"• <code>{r['user_id']}</code> — {escape(r['reason'])}" for r in rows
        ), parse_mode="HTML")
        return
    if len(parts) < 3 or not parts[2].split()[0].isdigit():
        await message.reply("Укажите корректный Telegram ID.")
        return
    user_id = int(parts[2].split()[0])
    if action == "add":
        reason = parts[2][len(str(user_id)):].strip()[:300] or "Причина не указана"
        await database.add_blacklist(user_id, message.from_user.id, reason)
        await message.answer(f"⛔ Пользователь <code>{user_id}</code> добавлен в общий чёрный список.", parse_mode="HTML")
    elif action == "del":
        removed = await database.remove_blacklist(user_id)
        await message.answer("✅ Запись удалена." if removed else "Пользователь не найден в списке.")
    else:
        await message.reply("Доступно: add, del, list.")


async def nickname_command(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _allowed(message, bot, owner_id):
        return
    from system_roles import has_permission
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if message.from_user.id != owner_id and member.status not in {"administrator", "creator"} and not await has_permission(message.from_user.id, owner_id, "moderation"):
        await message.reply("⛔ Никнеймы доступны модераторам и выше.")
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) >= 3 and parts[1].lower() == "set":
        target_id = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
            nickname = " ".join(parts[2:])
        else:
            try:
                target_id = int(parts[2].split(maxsplit=1)[0])
                nickname = parts[2].partition(" ")[2].strip()
            except (ValueError, IndexError):
                nickname = ""
        if not target_id or not nickname or len(nickname) > 32:
            await message.reply("Ответьте пользователю: /nick set Имя, либо /nick set ID Имя (до 32 символов).")
            return
        await database.set_nickname(message.chat.id, target_id, nickname)
        await message.answer(f"🏷 Никнейм установлен: <b>{escape(nickname)}</b>", parse_mode="HTML")
        return
    if message.reply_to_message and message.reply_to_message.from_user:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) == 2 and parts[1].isdigit():
        target_id = int(parts[1])
    else:
        await message.reply("Формат: ответьте на сообщение /nick set Имя или /nick ID.")
        return
    nickname = await database.get_nickname(message.chat.id, target_id)
    await message.answer(f"🏷 Никнейм: <b>{escape(nickname or 'не установлен')}</b>", parse_mode="HTML")


async def role_command(message: Message, bot: Bot, owner_id: int) -> None:
    if not await _allowed(message, bot, owner_id):
        return
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    from system_roles import has_permission
    if message.from_user.id != owner_id and member.status not in {"administrator", "creator"} and not await has_permission(message.from_user.id, owner_id, "staff_manage"):
        await message.reply("⛔ Управлять ролями могут владельцы, администраторы Telegram и руководство бота.")
        return
    parts = (message.text or "").split()
    if len(parts) == 1 or parts[1].lower() == "list":
        rows = await database.list_custom_moderators(message.chat.id)
        await message.answer("👮 Дополнительные модераторы:\n" + (
            "\n".join(f"• <code>{r['user_id']}</code>" for r in rows) if rows else "Список пуст."
        ), parse_mode="HTML")
        return
    if len(parts) != 3 or parts[1].lower() not in {"add", "del"} or not parts[2].isdigit():
        await message.reply("Формат: /role add ID, /role del ID или /role list.")
        return
    user_id = int(parts[2])
    if user_id == owner_id or await __import__("moderation").is_chat_admin(bot, message.chat.id, user_id):
        await message.reply("Владельца и администраторов Telegram нельзя переопределять.")
        return
    if parts[1].lower() == "add":
        await database.set_custom_moderator(message.chat.id, user_id, message.from_user.id)
        await message.answer(f"👮 <code>{user_id}</code> назначен модератором.", parse_mode="HTML")
    else:
        removed = await database.remove_custom_moderator(message.chat.id, user_id)
        await message.answer("Роль снята." if removed else "Пользователь не найден в списке.")
