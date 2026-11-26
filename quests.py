"""Quest board and reputation profile for the role-play game."""
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database
from game import display_name


def quests_keyboard(quests: list) -> InlineKeyboardMarkup:
    rows = []
    for quest in quests:
        if quest["completed_at"] is not None:
            continue
        if quest["ready"]:
            rows.append([InlineKeyboardButton(
                text=f"🎁 Забрать: {quest['title']}",
                callback_data=f"quest:claim:{quest['code']}",
            )])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔄 Обновить задания", callback_data="quest:refresh")]]
    )


def format_quests(quests: list) -> str:
    lines = ["📜 <b>Доска заданий</b>", ""]
    for quest in quests:
        if quest["completed_at"] is not None:
            status = "✅ Выполнено"
        elif quest["ready"]:
            status = "🎁 Можно получить награду"
        else:
            status = "⏳ Не выполнено"
        lines.append(
            f"<b>{escape(quest['title'])}</b>\n"
            f"{escape(quest['description'])}\n"
            f"Награда: 💰 {quest['reward_coins']} монет · "
            f"✨ {quest['reward_xp']} XP · ⭐ {quest['reward_reputation']} репутации\n"
            f"Статус: {status}"
        )
    if len(lines) == 2:
        lines.append("Сейчас заданий нет.")
    return "\n\n".join(lines)


def reputation_title(score: int) -> str:
    if score >= 50:
        return "Легенда города"
    if score >= 25:
        return "Уважаемый житель"
    if score >= 10:
        return "Известный житель"
    if score >= 3:
        return "Активный житель"
    return "Новичок"


def format_reputation(player) -> str:
    if player is None:
        return "⭐ <b>Репутация</b>\n\nИгровой профиль ещё не создан."
    score = int(player["reputation"])
    return (
        f"⭐ <b>Репутация: {escape(reputation_title(score))}</b>\n\n"
        f"👤 Игрок: {escape(player['username'] or 'Игрок')}\n"
        f"🌟 Очки репутации: <b>{score}</b>\n"
        f"✨ Опыт: <b>{player['xp']}</b>\n"
        f"💰 Баланс: <b>{player['coins']}</b> монет"
    )


async def show_quests(message: Message) -> None:
    if not message.from_user:
        return
    quests = await database.get_game_quests(message.from_user.id)
    await message.answer(
        format_quests(quests), parse_mode="HTML", reply_markup=quests_keyboard(quests)
    )


async def show_reputation(message: Message) -> None:
    if not message.from_user:
        return
    player = await database.get_game_reputation(message.from_user.id)
    await message.answer(format_reputation(player), parse_mode="HTML")


async def handle_quest_callback(callback) -> None:
    if callback.message is None or callback.from_user is None or not callback.data:
        await callback.answer()
        return
    if callback.data == "quest:refresh":
        quests = await database.get_game_quests(callback.from_user.id)
        await callback.message.answer(
            format_quests(quests), parse_mode="HTML", reply_markup=quests_keyboard(quests)
        )
        await callback.answer()
        return
    prefix = "quest:claim:"
    if not callback.data.startswith(prefix):
        await callback.answer()
        return
    code = callback.data[len(prefix):]
    status, coins, xp, reputation = await database.claim_game_quest(
        callback.from_user.id, display_name(callback.from_user), code
    )
    if status == "ok":
        await callback.answer("Задание выполнено! Награда начислена.")
        await callback.message.answer(
            "🎉 <b>Награда за задание</b>\n"
            f"💰 +{coins} монет\n✨ +{xp} XP\n⭐ +{reputation} репутации",
            parse_mode="HTML",
        )
    elif status == "not_ready":
        await callback.answer("Сначала выполни условие задания.", show_alert=True)
    elif status == "claimed":
        await callback.answer("Это задание уже выполнено.", show_alert=True)
    else:
        await callback.answer("Задание не найдено.", show_alert=True)
