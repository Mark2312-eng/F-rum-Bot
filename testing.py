"""Private-message test builder and one-time Telegram test invitations."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from database import database
from system_roles import has_permission

# Tests may grant any local role below the Chief Admin threshold.
AUTO_ASSIGNABLE_ROLE_MIN = 1
AUTO_ASSIGNABLE_ROLE_MAX = 79


def _is_auto_assignable_priority(priority: int) -> bool:
    return AUTO_ASSIGNABLE_ROLE_MIN <= priority <= AUTO_ASSIGNABLE_ROLE_MAX


async def _is_test_manager(user_id: int, owner_id: int) -> bool:
    """Only staff explicitly granted the test-management permission may build tests."""
    return await has_permission(user_id, owner_id, "testing_manage")


async def _can_review_tests(user_id: int, owner_id: int) -> bool:
    """Test reviewers and test managers may inspect test results."""
    return (
        await has_permission(user_id, owner_id, "testing_review")
        or await has_permission(user_id, owner_id, "testing_manage")
    )


async def _private_manager(message: Message, owner_id: int) -> bool:
    if message.chat.type != ChatType.PRIVATE or not message.from_user:
        await message.answer("Управление тестами доступно в личных сообщениях бота.")
        return False
    if not await _is_test_manager(message.from_user.id, owner_id):
        await message.answer("⛔ Для создания и редактирования тестов требуется должность с правом «Управление тестами».")
        return False
    return True


async def _private_reviewer(message: Message, owner_id: int) -> bool:
    if message.chat.type != ChatType.PRIVATE or not message.from_user:
        await message.answer("Просмотр результатов доступен в личных сообщениях бота.")
        return False
    if not await _can_review_tests(message.from_user.id, owner_id):
        await message.answer("⛔ Для просмотра результатов требуется право «Проверка тестов».")
        return False
    return True


def _parse_fields(text: str) -> list[str]:
    return [part.strip() for part in text.partition(" ")[2].split("|")]


async def create_test_command(message: Message, owner_id: int) -> None:
    if not await _private_manager(message, owner_id):
        return
    fields = _parse_fields(message.text or "")
    if len(fields) != 6:
        await message.answer(
            "Формат:\n<code>/createtest Название | ID_ГРУППЫ | КЛЮЧ_РОЛИ | проходной_балл | кулдаун_дни | лимит_минут</code>\n"
            "Пример: <code>/createtest Проверка модератора | -100123456789 | moderator | 80 | 7 | 30</code>",
            parse_mode="HTML",
        )
        return
    title, raw_chat_id, role_key, raw_score, raw_cooldown, raw_timer = fields
    try:
        chat_id = int(raw_chat_id)
        pass_score = int(raw_score)
        cooldown_days = int(raw_cooldown)
        time_limit = int(raw_timer)
    except ValueError:
        await message.answer("ID группы, проходной балл, кулдаун и таймер должны быть числами.")
        return
    if not 1 <= len(title) <= 120:
        await message.answer("Название должно содержать от 1 до 120 символов.")
        return
    pool = database._require_pool()
    if not await database.is_chat_registered(chat_id):
        await message.answer("Эта группа не подключена к боту. Сначала выполните /connect от имени владельца.")
        return
    role = await pool.fetchrow(
        """SELECT role_key, title, priority FROM chat_role_definitions
           WHERE chat_id = $1 AND role_key = $2""",
        chat_id, role_key,
    )
    if not role or not _is_auto_assignable_priority(int(role["priority"])):
        await message.answer(
            "Роль не найдена в этой группе или её приоритет вне диапазона 1–79. "
            "Посмотрите доступные ключи командой /roles."
        )
        return
    if not 1 <= pass_score <= 100 or not 0 <= cooldown_days <= 90 or not 1 <= time_limit <= 240:
        await message.answer("Допустимые значения: балл 1–100, кулдаун 0–90 дней, таймер 1–240 минут.")
        return

    test_id = await pool.fetchval(
        """INSERT INTO moderation_tests
           (title, creator_id, chat_id, role_key, pass_score, cooldown_days, time_limit_minutes)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
        title, message.from_user.id, chat_id, role_key, pass_score, cooldown_days, time_limit,
    )
    await message.answer(
        f"✅ Тест <b>#{test_id}</b> создан.\n"
        f"Название: <b>{escape(title)}</b>\n"
        f"Группа: <code>{chat_id}</code>\n"
        f"Проходной балл: <b>{pass_score}%</b>\n"
        f"Кулдаун: <b>{cooldown_days} дн.</b> · Таймер: <b>{time_limit} мин.</b>\n\n"
        f"Добавляйте вопросы командой <code>/testadd {test_id} | вопрос | правильный ответ | вариант 2 | вариант 3</code>.",
        parse_mode="HTML",
    )


async def add_question_command(message: Message, owner_id: int) -> None:
    if not await _private_manager(message, owner_id):
        return
    fields = _parse_fields(message.text or "")
    if len(fields) < 4 or len(fields) > 10:
        await message.answer(
            "Формат: <code>/testadd ID | вопрос | правильный ответ | неверный ответ 1 | неверный ответ 2</code>\n"
            "Нужно от 2 до 8 вариантов ответа.",
            parse_mode="HTML",
        )
        return
    try:
        test_id = int(fields[0])
    except ValueError:
        await message.answer("ID теста должен быть числом.")
        return
    prompt, options = fields[1], fields[2:]
    if not prompt or len(prompt) > 1000 or any(not option or len(option) > 180 for option in options):
        await message.answer("Вопрос не должен превышать 1000 символов, вариант ответа — 180 символов.")
        return
    pool = database._require_pool()
    test = await pool.fetchrow(
        "SELECT creator_id, is_active FROM moderation_tests WHERE id = $1", test_id
    )
    if not test or not test["is_active"]:
        await message.answer("Активный тест с таким ID не найден.")
        return
    if test["creator_id"] != message.from_user.id and message.from_user.id != owner_id:
        await message.answer("Редактировать этот тест может только его создатель или владелец бота.")
        return
    position = await pool.fetchval(
        "SELECT COALESCE(MAX(position), 0) + 1 FROM moderation_test_questions WHERE test_id = $1",
        test_id,
    )
    await pool.execute(
        """INSERT INTO moderation_test_questions
           (test_id, position, prompt, options, correct_option)
           VALUES ($1, $2, $3, $4::jsonb, 0)""",
        test_id, position, prompt, json.dumps(options, ensure_ascii=False),
    )
    await message.answer(f"✅ Вопрос №{position} добавлен в тест #{test_id}.")


async def send_test_command(message: Message, owner_id: int) -> None:
    if not await _private_manager(message, owner_id):
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].lstrip("-").isdigit() or not parts[2].isdigit():
        await message.answer("Формат: <code>/sendtest TELEGRAM_ID ID_ТЕСТА</code>", parse_mode="HTML")
        return
    target_id, test_id = int(parts[1]), int(parts[2])
    if target_id <= 0:
        await message.answer("Укажите положительный Telegram ID пользователя.")
        return
    pool = database._require_pool()
    test = await pool.fetchrow(
        """SELECT id, title, creator_id FROM moderation_tests
           WHERE id = $1 AND is_active = TRUE""",
        test_id,
    )
    if not test:
        await message.answer("Активный тест не найден.")
        return
    if test["creator_id"] != message.from_user.id and message.from_user.id != owner_id:
        await message.answer("Вы можете отправлять только собственные тесты.")
        return
    question_count = await pool.fetchval(
        "SELECT COUNT(*) FROM moderation_test_questions WHERE test_id = $1", test_id
    )
    if not question_count:
        await message.answer("Сначала добавьте хотя бы один вопрос командой /testadd.")
        return
    token = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    await pool.execute(
        """INSERT INTO moderation_test_invites
           (token_hash, test_id, target_user_id, issued_by, expires_at)
           VALUES ($1, $2, $3, $4, NOW() + INTERVAL '7 days')""",
        token_hash, test_id, target_id, message.from_user.id,
    )
    bot_user = await message.bot.get_me()
    link = f"https://t.me/{bot_user.username}?start=t_{token}"
    sent_directly = False
    try:
        await message.bot.send_message(
            target_id,
            f"Вам назначен тест «{escape(test['title'])}».\nОткройте ссылку, чтобы начать: {link}",
            parse_mode="HTML",
        )
        sent_directly = True
    except Exception:
        # Telegram does not let bots initiate a private conversation before /start.
        pass
    await message.answer(
        f"✅ Приглашение создано для <code>{target_id}</code>.\n"
        f"Личное сообщение отправлено: {'да' if sent_directly else 'нет — пользователь должен сначала открыть бота'}.\n"
        f"Ссылка действует 7 дней и привязана к указанному Telegram ID:\n{link}",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def _send_question(message: Message, session_id: int, question) -> None:
    options = question["options"]
    if isinstance(options, str):
        options = json.loads(options)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=str(option)[:64],
            callback_data=f"testq:{session_id}:{question['id']}:{index}",
        )]
        for index, option in enumerate(options)
    ])
    await message.answer(
        f"📝 <b>Вопрос {question['position']}</b>\n{escape(question['prompt'])}",
        parse_mode="HTML",
        reply_markup=keyboard,
    )


async def handle_test_start(message: Message) -> bool:
    """Consume /start t_TOKEN deep links. Return False for ordinary /start."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2 or not parts[1].startswith("t_"):
        return False
    if not message.from_user:
        await message.answer("Не удалось определить пользователя Telegram.")
        return True
    token = parts[1][2:]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    pool = database._require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            invite = await connection.fetchrow(
                """SELECT i.token_hash, i.test_id, i.target_user_id, i.expires_at, i.used_at,
                          t.title, t.time_limit_minutes
                   FROM moderation_test_invites i
                   JOIN moderation_tests t ON t.id = i.test_id
                   WHERE i.token_hash = $1 AND t.is_active = TRUE
                   FOR UPDATE OF i""",
                token_hash,
            )
            if not invite or invite["used_at"] is not None or invite["expires_at"] <= datetime.now(timezone.utc):
                await message.answer("Приглашение недействительно, уже использовано или истекло.")
                return True
            if invite["target_user_id"] != message.from_user.id:
                await message.answer("Эта ссылка выдана другому Telegram-пользователю.")
                return True
            cooldown = await connection.fetchval(
                """SELECT available_at FROM moderation_test_cooldowns
                   WHERE test_id = $1 AND user_id = $2""",
                invite["test_id"], message.from_user.id,
            )
            now = datetime.now(timezone.utc)
            if cooldown and cooldown > now:
                await message.answer(f"Повторная попытка будет доступна: {cooldown:%d.%m.%Y %H:%M UTC}.")
                return True
            question_count = await connection.fetchval(
                "SELECT COUNT(*) FROM moderation_test_questions WHERE test_id = $1",
                invite["test_id"],
            )
            if not question_count:
                await message.answer("В тесте пока нет вопросов. Обратитесь к организатору.")
                return True
            await connection.execute(
                "UPDATE moderation_test_invites SET used_at = NOW() WHERE token_hash = $1",
                token_hash,
            )
            session_id = await connection.fetchval(
                """INSERT INTO moderation_test_sessions
                   (token_hash, test_id, user_id, expires_at)
                   VALUES ($1, $2, $3, NOW() + ($4 * INTERVAL '1 minute'))
                   RETURNING id""",
                token_hash, invite["test_id"], message.from_user.id, invite["time_limit_minutes"],
            )
            first_question = await connection.fetchrow(
                """SELECT id, position, prompt, options FROM moderation_test_questions
                   WHERE test_id = $1 ORDER BY position LIMIT 1""",
                invite["test_id"],
            )
    await message.answer(
        f"Тест «{escape(invite['title'])}» начат. На прохождение отведено "
        f"{invite['time_limit_minutes']} минут.",
        parse_mode="HTML",
    )
    await _send_question(message, session_id, first_question)
    return True


async def test_answer_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or callback.message is None:
        await callback.answer("Не удалось обработать ответ.", show_alert=True)
        return
    try:
        _, raw_session_id, raw_question_id, raw_choice = callback.data.split(":")
        session_id, question_id, choice = int(raw_session_id), int(raw_question_id), int(raw_choice)
    except (ValueError, TypeError):
        await callback.answer("Некорректный ответ.", show_alert=True)
        return

    pool = database._require_pool()
    next_question = None
    outcome = None
    async with pool.acquire() as connection:
        async with connection.transaction():
            session = await connection.fetchrow(
                """SELECT s.id, s.test_id, s.user_id, s.current_position, s.score,
                          s.expires_at, s.status, t.pass_score, t.cooldown_days,
                          t.chat_id, t.role_key, t.creator_id
                   FROM moderation_test_sessions s
                   JOIN moderation_tests t ON t.id = s.test_id
                   WHERE s.id = $1 FOR UPDATE OF s""",
                session_id,
            )
            if not session or session["user_id"] != callback.from_user.id:
                await callback.answer("Этот тест принадлежит другому пользователю.", show_alert=True)
                return
            if session["status"] != "active":
                await callback.answer("Тест уже завершён.", show_alert=True)
                return
            if session["expires_at"] <= datetime.now(timezone.utc):
                await connection.execute(
                    "UPDATE moderation_test_sessions SET status = 'expired', completed_at = NOW() WHERE id = $1",
                    session_id,
                )
                await callback.answer("Время прохождения истекло.", show_alert=True)
                return
            question = await connection.fetchrow(
                """SELECT id, position, options, correct_option FROM moderation_test_questions
                   WHERE id = $1 AND test_id = $2""",
                question_id, session["test_id"],
            )
            if not question or question["position"] != session["current_position"]:
                await callback.answer("Этот вопрос уже обработан.", show_alert=True)
                return
            options = question["options"]
            if isinstance(options, str):
                options = json.loads(options)
            if choice < 0 or choice >= len(options):
                await callback.answer("Вариант ответа не найден.", show_alert=True)
                return
            new_score = session["score"] + int(choice == question["correct_option"])
            question_count = await connection.fetchval(
                "SELECT COUNT(*) FROM moderation_test_questions WHERE test_id = $1",
                session["test_id"],
            )
            next_position = session["current_position"] + 1
            if next_position <= question_count:
                await connection.execute(
                    """UPDATE moderation_test_sessions
                       SET current_position = $2, score = $3 WHERE id = $1""",
                    session_id, next_position, new_score,
                )
                next_question = await connection.fetchrow(
                    """SELECT id, position, prompt, options FROM moderation_test_questions
                       WHERE test_id = $1 AND position = $2""",
                    session["test_id"], next_position,
                )
            else:
                percent = round(new_score * 100 / question_count)
                passed = percent >= session["pass_score"]
                status = "passed" if passed else "failed"
                await connection.execute(
                    """UPDATE moderation_test_sessions
                       SET score = $2, status = $3, completed_at = NOW() WHERE id = $1""",
                    session_id, new_score, status,
                )
                result_id = await connection.fetchval(
                    """INSERT INTO moderation_test_results
                       (test_id, user_id, score_percent, passed, role_assigned)
                       VALUES ($1, $2, $3, $4, NULL) RETURNING id""",
                    session["test_id"], callback.from_user.id, percent, passed,
                )
                if not passed and session["cooldown_days"] > 0:
                    await connection.execute(
                        """INSERT INTO moderation_test_cooldowns (test_id, user_id, available_at)
                           VALUES ($1, $2, NOW() + ($3 * INTERVAL '1 day'))
                           ON CONFLICT (test_id, user_id) DO UPDATE
                           SET available_at = EXCLUDED.available_at""",
                        session["test_id"], callback.from_user.id, session["cooldown_days"],
                    )
                outcome = (
                    passed, percent, session["chat_id"], session["role_key"],
                    session["creator_id"], session["test_id"], result_id,
                )

    await callback.answer("Ответ принят.")
    if next_question:
        await _send_question(callback.message, session_id, next_question)
        return
    passed, percent, chat_id, role_key, creator_id, test_id, result_id = outcome
    if passed:
        assignment_reason = None
        try:
            member = await callback.bot.get_chat_member(chat_id, callback.from_user.id)
            if member.status in {"creator", "administrator"}:
                assignment_reason = "участник является администратором Telegram"
        except Exception:
            assignment_reason = "не удалось проверить статус участника в Telegram"
        assigned = False
        if assignment_reason is None:
            assigned = await database.assign_test_role_guarded(
                chat_id, callback.from_user.id, role_key, creator_id,
            )
            if not assigned:
                assignment_reason = "роль не назначена из-за приоритета или иммунитета участника"
        if assigned:
            pool = database._require_pool()
            await pool.execute(
                "UPDATE moderation_test_results SET role_assigned = $2 WHERE id = $1",
                result_id, role_key,
            )
            role_row = await database.get_chat_member_role(chat_id, callback.from_user.id)
            role_title = role_row["title"] if role_row else role_key
            await callback.message.answer(
                f"✅ Тест завершён: <b>{percent}%</b>. Вам назначена роль "
                f"<b>{escape(role_title)}</b> в целевой группе.",
                parse_mode="HTML",
            )
            group_notice = (
                f"🎓 Пользователь <code>{callback.from_user.id}</code> успешно прошёл тест "
                f"и получил роль <b>{escape(role_title)}</b>."
            )
        else:
            await callback.message.answer(
                f"✅ Тест пройден: <b>{percent}%</b>. Автоматическое назначение роли "
                f"<code>{escape(role_key)}</code> не выполнено: {escape(assignment_reason)}. "
                "Результат теста сохранён.",
                parse_mode="HTML",
            )
            group_notice = (
                f"🎓 Пользователь <code>{callback.from_user.id}</code> прошёл тест "
                f"({percent}%), но роль <code>{escape(role_key)}</code> не назначена: "
                f"{escape(assignment_reason)}."
            )
        try:
            await callback.bot.send_message(chat_id, group_notice, parse_mode="HTML")
        except Exception:
            pass
    else:
        await callback.message.answer(
            f"Тест завершён: <b>{percent}%</b>. Проходной балл не набран. "
            "Повторная попытка будет доступна после окончания кулдауна.",
            parse_mode="HTML",
        )


async def test_results_command(message: Message, owner_id: int) -> None:
    if not await _private_reviewer(message, owner_id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Формат: <code>/testresults ID_ТЕСТА</code>", parse_mode="HTML")
        return
    test_id = int(parts[1])
    pool = database._require_pool()
    test = await pool.fetchrow(
        "SELECT creator_id, title FROM moderation_tests WHERE id = $1", test_id
    )
    if not test:
        await message.answer("Тест не найден.")
        return
    if test["creator_id"] != message.from_user.id and message.from_user.id != owner_id:
        await message.answer("Просматривать результаты может только создатель теста или владелец бота.")
        return
    rows = await pool.fetch(
        """SELECT user_id, score_percent, passed, created_at
           FROM moderation_test_results WHERE test_id = $1
           ORDER BY created_at DESC LIMIT 30""",
        test_id,
    )
    if not rows:
        await message.answer(f"По тесту «{escape(test['title'])}» результатов пока нет.")
        return
    lines = [f"📊 <b>Результаты теста #{test_id}: {escape(test['title'])}</b>"]
    for row in rows:
        status = "пройден" if row["passed"] else "не пройден"
        lines.append(
            f"• <code>{row['user_id']}</code> — {row['score_percent']}% ({status})"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")
