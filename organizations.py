"""Faction and family features for the role-play game."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database
from game import display_name


def factions_keyboard(factions: list, current) -> InlineKeyboardMarkup:
    rows = []
    if current is None:
        rows.extend([
            [InlineKeyboardButton(
                text=f"➕ Вступить: {item['name']}",
                callback_data=f"org:faction_join:{item['id']}",
            )]
            for item in factions
        ])
    else:
        rows.append([InlineKeyboardButton(
            text="🚪 Покинуть фракцию", callback_data="org:faction_leave"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_factions(factions: list, current) -> str:
    lines = ["🏛 <b>Фракции игрового мира</b>", ""]
    for item in factions:
        lines.append(
            f"🏢 <b>{escape(item['name'])}</b>\n"
            f"{escape(item['description'])}\n"
            f"👥 Участников: <b>{item['members']}</b>"
        )
    if current:
        lines.extend([
            "",
            f"Твоя фракция: <b>{escape(current['name'])}</b>",
            f"Ранг: <b>{escape(current['rank_name'])}</b>",
        ])
    else:
        lines.extend(["", "Ты пока не состоишь во фракции."])
    return "\n\n".join(lines)


def format_family(family, members: list | None = None) -> str:
    if family is None:
        return (
            "👨‍👩‍👧‍👦 <b>Семья</b>\n\n"
            "Ты пока не состоишь в семье.\n"
            "Создать: <code>/family create Название</code>\n"
            "Вступить: <code>/family join ID</code>"
        )
    lines = [
        f"👨‍👩‍👧‍👦 <b>Семья «{escape(family['name'])}»</b>",
        f"🆔 ID семьи: <code>{family['id']}</code>",
        f"👥 Участников: <b>{family['members']}/10</b>",
        f"👑 Твоя роль: <b>{escape(family['role'])}</b>",
    ]
    if members is not None:
        lines.extend(["", "<b>Состав семьи</b>"])
        lines.extend(
            f"• {escape(str(item['username'] or f'Игрок {item['user_id']}'))} — "
            f"{'глава' if item['role'] == 'owner' else 'участник'}"
            for item in members
        )
    return "\n".join(lines)


async def show_factions(message: Message) -> None:
    if not message.from_user:
        return
    factions = await database.get_game_factions()
    current = await database.get_game_faction(message.from_user.id)
    await message.answer(
        format_factions(factions, current), parse_mode="HTML",
        reply_markup=factions_keyboard(factions, current),
    )


async def manage_family(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    args = (command.args or "").strip()
    parts = args.split(maxsplit=1)
    action = parts[0].lower() if parts else "info"
    user_id = message.from_user.id
    username = display_name(message.from_user)

    if action == "create":
        name = parts[1] if len(parts) > 1 else ""
        success, result = await database.create_game_family(user_id, username, name)
        await message.answer(("✅ " if success else "⚠️ ") + escape(result), parse_mode="HTML")
    elif action == "join":
        try:
            family_id = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            family_id = 0
        success, result = await database.join_game_family(user_id, family_id)
        await message.answer(("✅ " if success else "⚠️ ") + escape(result), parse_mode="HTML")
    elif action == "leave":
        success, result = await database.leave_game_family(user_id)
        await message.answer(("✅ " if success else "⚠️ ") + escape(result), parse_mode="HTML")
    elif action == "info":
        family = await database.get_game_family(user_id)
        await message.answer(format_family(family), parse_mode="HTML")
    else:
        await message.answer(
            "Использование:\n"
            "<code>/family</code> — информация\n"
            "<code>/family create Название</code> — создать\n"
            "<code>/family join ID</code> — вступить\n"
            "<code>/family leave</code> — покинуть",
            parse_mode="HTML",
        )


async def handle_org_callback(callback) -> None:
    if callback.message is None or callback.from_user is None or not callback.data:
        await callback.answer()
        return
    data = callback.data
    user_id = callback.from_user.id
    if data.startswith("org:faction_join:"):
        try:
            faction_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await callback.answer("Некорректная фракция.", show_alert=True)
            return
        success, result = await database.join_game_faction(
            user_id, display_name(callback.from_user), faction_id
        )
        await callback.answer(result, show_alert=not success)
    elif data == "org:faction_leave":
        success = await database.leave_game_faction(user_id)
        await callback.answer(
            "Ты покинул фракцию." if success else "Ты не состоишь во фракции.",
            show_alert=not success,
        )
    else:
        await callback.answer()
        return
    factions = await database.get_game_factions()
    current = await database.get_game_faction(user_id)
    await callback.message.answer(
        format_factions(factions, current), parse_mode="HTML",
        reply_markup=factions_keyboard(factions, current),
    )
