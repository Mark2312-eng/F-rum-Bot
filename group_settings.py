"""Per-group moderation settings UI and authorization."""
import os

from aiogram import Bot
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import database
from moderation import is_chat_admin

FLOOD_LABELS = {
    "off": "Выключен",
    "balanced": "Сбалансированный (6 сообщений за 8 секунд)",
    "strict": "Строгий (4 сообщения за 8 секунд)",
}
LINK_LABELS = {
    "allow": "Разрешать",
    "block": "Удалять ссылки",
    "mute": "Удалять и ограничивать на 5 минут",
}


def settings_keyboard(mode: str, link_policy: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=("✓ " if mode == "off" else "") + "Антифлуд: выкл.", callback_data="cfg:flood:off"),
            InlineKeyboardButton(text=("✓ " if mode == "balanced" else "") + "Баланс", callback_data="cfg:flood:balanced"),
            InlineKeyboardButton(text=("✓ " if mode == "strict" else "") + "Строго", callback_data="cfg:flood:strict"),
        ],
        [
            InlineKeyboardButton(text=("✓ " if link_policy == "allow" else "") + "Ссылки: разрешить", callback_data="cfg:links:allow"),
        ],
        [
            InlineKeyboardButton(text=("✓ " if link_policy == "block" else "") + "Ссылки: удалять", callback_data="cfg:links:block"),
        ],
        [
            InlineKeyboardButton(text=("✓ " if link_policy == "mute" else "") + "Ссылки: ограничивать", callback_data="cfg:links:mute"),
        ],
    ])


def settings_text(settings: dict[str, str]) -> str:
    return (
        "⚙️ <b>Настройки модерации группы</b>\n\n"
        f"Антифлуд: <b>{FLOOD_LABELS[settings['moderation_mode']]}</b>\n"
        f"Ссылки: <b>{LINK_LABELS[settings['link_policy']]}</b>\n\n"
        "Настройки сохраняются отдельно для этой группы."
    )


async def _authorized(chat_id: int, user_id: int, bot: Bot, owner_id: int) -> bool:
    if user_id == owner_id:
        return True
    return await is_chat_admin(bot, chat_id, user_id)


async def show_group_settings(message: Message, bot: Bot, owner_id: int) -> None:
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.answer("Команда /settings доступна внутри подключённой группы.")
        return
    if not await database.is_chat_registered(message.chat.id):
        await message.answer("Сначала подключите группу командой /connect от имени владельца бота.")
        return
    if not message.from_user or not await _authorized(
        message.chat.id, message.from_user.id, bot, owner_id
    ):
        await message.answer("⛔ Настройки доступны только владельцу бота и администраторам группы.")
        return
    settings = await database.get_chat_settings(message.chat.id)
    await message.answer(
        settings_text(settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(settings["moderation_mode"], settings["link_policy"]),
    )


async def apply_setting_callback(callback: CallbackQuery, bot: Bot, owner_id: int) -> None:
    message = callback.message
    if message is None or message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await callback.answer("Откройте настройки в группе.", show_alert=True)
        return
    if not await database.is_chat_registered(message.chat.id):
        await callback.answer("Эта группа не подключена.", show_alert=True)
        return
    if not await _authorized(message.chat.id, callback.from_user.id, bot, owner_id):
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    parts = (callback.data or "").split(":")
    if len(parts) != 3:
        await callback.answer("Некорректная настройка.", show_alert=True)
        return
    _, category, value = parts
    mapping = {
        "flood": ("moderation_mode", FLOOD_LABELS),
        "links": ("link_policy", LINK_LABELS),
    }
    if category not in mapping or value not in mapping[category][1]:
        await callback.answer("Неизвестное значение настройки.", show_alert=True)
        return

    column, _labels = mapping[category]
    await database.update_chat_setting(message.chat.id, column, value)
    settings = await database.get_chat_settings(message.chat.id)
    await message.edit_text(
        settings_text(settings),
        parse_mode="HTML",
        reply_markup=settings_keyboard(settings["moderation_mode"], settings["link_policy"]),
    )
    await callback.answer("Настройка сохранена.")


