"""Player-facing game profile, daily rewards, leaderboard and achievements."""
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database

ACHIEVEMENTS = {
    "first_steps": ("🌱 Первые шаги", "Получить первые 50 XP"),
    "experienced": ("⭐ Опытный игрок", "Набрать 500 XP"),
    "wealthy": ("💰 Копилка", "Накопить 1 000 игровых монет"),
    "reputation": ("🏅 Уважаемый", "Набрать 100 очков репутации"),
}


def display_name(user) -> str:
    return (user.full_name or user.username or f"Игрок {user.id}")[:64]


def game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎁 Ежедневная награда", callback_data="game:daily"),
            InlineKeyboardButton(text="🏆 Рейтинг", callback_data="game:top"),
        ],
        [InlineKeyboardButton(text="🎖 Достижения", callback_data="game:achievements")],
    ])


def format_game_profile(profile, achievements: list) -> str:
    xp = int(profile["xp"])
    level = xp // 100 + 1
    progress = xp % 100
    name = escape(profile["username"] or f"Игрок {profile['user_id']}")
    return (
        f"🎮 <b>Игровой паспорт: {name}</b>\n\n"
        f"🆔 Telegram ID: <code>{profile['user_id']}</code>\n"
        f"⭐ Уровень: <b>{level}</b> ({progress}/100 XP)\n"
        f"✨ Опыт: <b>{xp}</b>\n"
        f"💰 Баланс: <b>{profile['coins']}</b> монет\n"
        f"🏅 Репутация: <b>{profile['reputation']}</b>\n"
        f"🔥 Серия ежедневных входов: <b>{profile['daily_streak']}</b>\n"
        f"🎖 Достижений: <b>{len(achievements)}</b>"
    )


def format_leaderboard(players: list) -> str:
    if not players:
        return "🏆 <b>Рейтинг игроков</b>\n\nПока никто не создал игровой профиль."
    lines = ["🏆 <b>Рейтинг игроков по опыту</b>", ""]
    for index, player in enumerate(players, start=1):
        name = escape(player["username"] or f"Игрок {player['user_id']}")
        level = int(player["xp"]) // 100 + 1
        lines.append(f"{index}. <b>{name}</b> — уровень {level}, {player['xp']} XP")
    return "\n".join(lines)


def format_achievements(achievements: list) -> str:
    unlocked = {row["achievement_code"] for row in achievements}
    lines = ["🎖 <b>Достижения</b>", ""]
    for code, (title, description) in ACHIEVEMENTS.items():
        mark = "✅" if code in unlocked else "🔒"
        lines.append(f"{mark} <b>{title}</b> — {description}")
    return "\n".join(lines)


async def show_game_profile(message: Message) -> None:
    if not message.from_user:
        return
    profile = await database.get_game_profile(message.from_user.id, display_name(message.from_user))
    achievements = await database.sync_game_achievements(message.from_user.id)
    await message.answer(format_game_profile(profile, achievements), parse_mode="HTML", reply_markup=game_keyboard())


async def claim_daily_reward(message: Message) -> None:
    if not message.from_user:
        return
    profile, reward, claimed = await database.claim_game_daily(
        message.from_user.id, display_name(message.from_user)
    )
    if not claimed:
        await message.answer("⏳ Ежедневная награда уже получена. Возвращайся завтра.")
        return
    achievements = await database.sync_game_achievements(message.from_user.id)
    await message.answer(
        f"🎁 Ежедневная награда получена!\n💰 +{reward} монет\n✨ +50 XP\n"
        f"🔥 Серия: {profile['daily_streak']} дн.\n\n"
        + format_game_profile(profile, achievements),
        parse_mode="HTML", reply_markup=game_keyboard(),
    )


async def show_leaderboard(message: Message) -> None:
    await message.answer(format_leaderboard(await database.get_game_leaderboard(10)), parse_mode="HTML")


async def show_achievements(message: Message) -> None:
    if not message.from_user:
        return
    await database.get_game_profile(message.from_user.id, display_name(message.from_user))
    achievements = await database.sync_game_achievements(message.from_user.id)
    await message.answer(format_achievements(achievements), parse_mode="HTML")


async def handle_game_callback(callback) -> None:
    if callback.data == "game:daily" and callback.message and callback.from_user:
        profile, reward, claimed = await database.claim_game_daily(
            callback.from_user.id, display_name(callback.from_user)
        )
        if not claimed:
            await callback.answer("Награда уже получена сегодня.", show_alert=True)
            return
        achievements = await database.sync_game_achievements(callback.from_user.id)
        await callback.message.answer(
            f"🎁 Получено: +{reward} монет и +50 XP.\n\n"
            + format_game_profile(profile, achievements),
            parse_mode="HTML", reply_markup=game_keyboard(),
        )
    elif callback.data == "game:top" and callback.message:
        await callback.message.answer(
            format_leaderboard(await database.get_game_leaderboard(10)), parse_mode="HTML"
        )
    elif callback.data == "game:achievements" and callback.message and callback.from_user:
        await database.get_game_profile(callback.from_user.id, display_name(callback.from_user))
        achievements = await database.sync_game_achievements(callback.from_user.id)
        await callback.message.answer(format_achievements(achievements), parse_mode="HTML")
    await callback.answer()
