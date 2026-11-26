"""In-game employment, vacancies and shift rewards."""
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database
from game import display_name


def jobs_keyboard(jobs: list) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"📋 {job['name']} · {job['reward_coins']} монет/смена",
            callback_data=f"work:apply:{job['id']}",
        )]
        for job in jobs
    ]
    rows.append([InlineKeyboardButton(text="↩️ В меню работы", callback_data="work:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def work_keyboard(employed: bool) -> InlineKeyboardMarkup:
    if employed:
        rows = [
            [InlineKeyboardButton(text="🏁 Начать смену", callback_data="work:shift")],
            [InlineKeyboardButton(text="❌ Уволиться", callback_data="work:quit")],
            [InlineKeyboardButton(text="📋 Вакансии", callback_data="work:jobs")],
        ]
    else:
        rows = [[InlineKeyboardButton(text="📋 Посмотреть вакансии", callback_data="work:jobs")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_jobs(jobs: list) -> str:
    if not jobs:
        return "📋 <b>Вакансии</b>\n\nСейчас открытых вакансий нет."
    lines = ["📋 <b>Открытые вакансии</b>", ""]
    for job in jobs:
        lines.append(
            f"💼 <b>{escape(job['name'])}</b>\n"
            f"{escape(job['description'])}\n"
            f"💰 Оплата за смену: <b>{job['reward_coins']}</b> монет"
        )
    return "\n\n".join(lines)


def format_employment(employment) -> str:
    if employment is None:
        return "💼 <b>Работа</b>\n\nУ тебя пока нет работы. Посмотри доступные вакансии."
    return (
        f"💼 <b>Работа: {escape(employment['job_name'])}</b>\n\n"
        f"🎖 Ранг: <b>{escape(employment['rank_name'])}</b>\n"
        f"📊 Завершено смен: <b>{employment['shifts_completed']}</b>\n"
        f"💰 Оплата за смену: <b>{employment['reward_coins']}</b> монет\n"
        "⏱ Между сменами действует перерыв 10 минут."
    )


async def show_work(message: Message) -> None:
    if not message.from_user:
        return
    employment = await database.get_game_employment(message.from_user.id)
    await message.answer(
        format_employment(employment), parse_mode="HTML",
        reply_markup=work_keyboard(employment is not None),
    )


async def show_jobs(message: Message) -> None:
    jobs = await database.get_game_jobs()
    await message.answer(format_jobs(jobs), parse_mode="HTML", reply_markup=jobs_keyboard(jobs))


async def handle_work_callback(callback) -> None:
    if callback.message is None or callback.from_user is None or not callback.data:
        await callback.answer()
        return
    user_id = callback.from_user.id
    data = callback.data

    if data == "work:home":
        employment = await database.get_game_employment(user_id)
        await callback.message.answer(
            format_employment(employment), parse_mode="HTML",
            reply_markup=work_keyboard(employment is not None),
        )
    elif data == "work:jobs":
        jobs = await database.get_game_jobs()
        await callback.message.answer(format_jobs(jobs), parse_mode="HTML", reply_markup=jobs_keyboard(jobs))
    elif data.startswith("work:apply:"):
        try:
            job_id = int(data.rsplit(":", 1)[1])
        except ValueError:
            await callback.answer("Некорректная вакансия.", show_alert=True)
            return
        success, result = await database.apply_game_job(
            user_id, display_name(callback.from_user), job_id
        )
        await callback.answer(result, show_alert=not success)
        if success:
            employment = await database.get_game_employment(user_id)
            await callback.message.answer(
                format_employment(employment), parse_mode="HTML",
                reply_markup=work_keyboard(True),
            )
        return
    elif data == "work:shift":
        status, employment, reward = await database.perform_game_shift(user_id)
        if status == "no_job":
            await callback.answer("Сначала устройся на работу.", show_alert=True)
            return
        if status == "cooldown":
            await callback.answer("Следующую смену можно начать через 10 минут после предыдущей.", show_alert=True)
            return
        await callback.answer(f"Смена завершена: +{reward} монет и +35 XP.")
        await callback.message.answer(
            "✅ <b>Смена завершена!</b>\n"
            f"💰 Получено: <b>+{reward}</b> монет\n"
            "✨ Опыт: <b>+35 XP</b>\n\n"
            + format_employment(employment),
            parse_mode="HTML", reply_markup=work_keyboard(True),
        )
        return
    elif data == "work:quit":
        quit_result = await database.quit_game_job(user_id)
        await callback.answer("Ты уволился." if quit_result else "У тебя нет работы.")
        employment = await database.get_game_employment(user_id)
        await callback.message.answer(
            format_employment(employment), parse_mode="HTML",
            reply_markup=work_keyboard(False),
        )
        return
    await callback.answer()
