"""Free community contests, promo codes and non-monetary engagement rewards."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from html import escape

from aiogram import Dispatcher, F
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database


ACHIEVEMENTS = (
    (100, "Первый шаг", "Получить первые 100 баллов"),
    (500, "Активный участник", "Набрать 500 баллов"),
    (1500, "Постоянный участник", "Набрать 1 500 баллов"),
    (5000, "Легенда сообщества", "Набрать 5 000 баллов"),
)


def parse_contest_input(raw: str):
    """Parse title | ISO-8601 deadline with timezone | winners | prize."""
    parts = [part.strip() for part in raw.split("|", 3)]
    if len(parts) != 4 or not all(parts):
        raise ValueError("Формат: название | 2026-12-20T18:00+03:00 | число победителей | приз")
    try:
        ends_at = datetime.fromisoformat(parts[1])
        winners = int(parts[2])
    except (ValueError, TypeError) as exc:
        raise ValueError("Проверь дату и количество победителей.") from exc
    if ends_at.tzinfo is None or ends_at.utcoffset() is None:
        raise ValueError("У даты должен быть часовой пояс, например +03:00.")
    if ends_at <= datetime.now(timezone.utc):
        raise ValueError("Дата завершения должна быть в будущем.")
    if not 1 <= winners <= 50:
        raise ValueError("Количество победителей должно быть от 1 до 50.")
    if len(parts[0]) > 100 or len(parts[3]) > 300:
        raise ValueError("Название — до 100 символов, описание приза — до 300.")
    return parts[0], ends_at, winners, parts[3]


def normalize_promo_code(raw: str) -> str:
    code = raw.strip().upper()
    if not 3 <= len(code) <= 32 or not code.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Код должен содержать 3–32 символа: латинские буквы, цифры, _ или -.")
    return code


async def ensure_community_rewards_schema() -> None:
    pool = database._require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS community_contests (
                    id BIGSERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    created_by BIGINT NOT NULL,
                    title TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 100),
                    prize TEXT NOT NULL CHECK (char_length(prize) BETWEEN 1 AND 300),
                    ends_at TIMESTAMPTZ NOT NULL,
                    winner_count INTEGER NOT NULL CHECK (winner_count BETWEEN 1 AND 50),
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'drawn', 'cancelled')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    drawn_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS community_contests_chat_idx
                    ON community_contests (chat_id, status, ends_at);
                CREATE TABLE IF NOT EXISTS community_contest_entries (
                    contest_id BIGINT NOT NULL REFERENCES community_contests(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (contest_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS community_contest_winners (
                    contest_id BIGINT NOT NULL REFERENCES community_contests(id) ON DELETE CASCADE,
                    user_id BIGINT NOT NULL,
                    place INTEGER NOT NULL,
                    selected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (contest_id, user_id),
                    UNIQUE (contest_id, place)
                );
                CREATE TABLE IF NOT EXISTS community_points (
                    user_id BIGINT PRIMARY KEY,
                    points BIGINT NOT NULL DEFAULT 0 CHECK (points >= 0),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS community_points_ledger (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    amount INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS community_points_rank_idx
                    ON community_points (points DESC, user_id);
                CREATE TABLE IF NOT EXISTS community_promo_codes (
                    code TEXT PRIMARY KEY,
                    points INTEGER NOT NULL CHECK (points BETWEEN 1 AND 10000),
                    max_uses INTEGER NOT NULL CHECK (max_uses BETWEEN 1 AND 100000),
                    uses INTEGER NOT NULL DEFAULT 0,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_by BIGINT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS community_promo_redemptions (
                    code TEXT NOT NULL REFERENCES community_promo_codes(code),
                    user_id BIGINT NOT NULL,
                    redeemed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (code, user_id)
                );
                CREATE TABLE IF NOT EXISTS community_daily_claims (
                    user_id BIGINT NOT NULL,
                    claim_date DATE NOT NULL,
                    points INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, claim_date)
                );
                CREATE TABLE IF NOT EXISTS community_achievements (
                    user_id BIGINT NOT NULL,
                    achievement_key TEXT NOT NULL,
                    awarded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (user_id, achievement_key)
                );
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                INSERT INTO schema_migrations (version, description)
                VALUES ('0007_community_contests_rewards',
                        'Free contests, points, promo codes, daily rewards and achievements')
                ON CONFLICT (version) DO NOTHING;
            """)


def _is_owner(user_id: int | None) -> bool:
    try:
        owner_id = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
    except ValueError:
        owner_id = 0
    return bool(user_id and owner_id > 0 and user_id == owner_id)


async def _add_points(conn, user_id: int, amount: int, reason: str) -> None:
    await conn.execute("""
        INSERT INTO community_points (user_id, points) VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE
        SET points = community_points.points + EXCLUDED.points, updated_at = NOW()
    """, user_id, amount)
    await conn.execute(
        "INSERT INTO community_points_ledger (user_id, amount, reason) VALUES ($1,$2,$3)",
        user_id, amount, reason[:120],
    )
    points = await conn.fetchval("SELECT points FROM community_points WHERE user_id=$1", user_id)
    for threshold, _title, _description in ACHIEVEMENTS:
        if points >= threshold:
            key = str(threshold)
            await conn.execute("""
                INSERT INTO community_achievements (user_id, achievement_key)
                VALUES ($1,$2) ON CONFLICT DO NOTHING
            """, user_id, key)


async def create_contest_command(message: Message) -> None:
    if not _is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Создавать конкурсы может только владелец проекта.")
        return
    if message.chat.type == "private":
        await message.answer("Создавай конкурс в той группе, где он должен быть опубликован.")
        return
    try:
        title, ends_at, winners, prize = parse_contest_input((message.text or "").partition(" ")[2])
    except ValueError as exc:
        await message.answer(f"⚠️ {escape(str(exc))}")
        return
    async with database._require_pool().acquire() as conn:
        contest_id = await conn.fetchval("""
            INSERT INTO community_contests
                (chat_id, created_by, title, prize, ends_at, winner_count)
            VALUES ($1,$2,$3,$4,$5,$6) RETURNING id
        """, message.chat.id, message.from_user.id, title, prize, ends_at, winners)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎉 Участвовать", callback_data=f"contest:join:{contest_id}")
    ]])
    await message.answer(
        f"🎉 <b>КОНКУРС #{contest_id}</b>\n\n"
        f"<b>{escape(title)}</b>\n🎁 Приз: {escape(prize)}\n"
        f"🏆 Победителей: {winners}\n⏰ Завершение: {ends_at.isoformat()}\n\n"
        "Участие бесплатное. Победители будут выбраны случайно из списка участников.",
        parse_mode="HTML", reply_markup=keyboard,
    )


async def list_contests_command(message: Message) -> None:
    async with database._require_pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.id,c.title,c.prize,c.ends_at,c.winner_count,c.status,
                   COUNT(e.user_id)::int AS entries
            FROM community_contests c
            LEFT JOIN community_contest_entries e ON e.contest_id=c.id
            WHERE c.chat_id=$1 AND c.status <> 'cancelled'
            GROUP BY c.id ORDER BY c.created_at DESC LIMIT 10
        """, message.chat.id)
    if not rows:
        await message.answer("🎉 Конкурсов пока нет.")
        return
    for row in rows:
        state = "идёт" if row["status"] == "open" else "завершён"
        keyboard = None
        if row["status"] == "open" and row["ends_at"] > datetime.now(timezone.utc):
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🎉 Участвовать", callback_data=f"contest:join:{row['id']}")
            ]])
        await message.answer(
            f"🎉 <b>#{row['id']} · {escape(row['title'])}</b>\n"
            f"🎁 {escape(row['prize'])}\n👥 Участников: {row['entries']}\n"
            f"🏆 Победителей: {row['winner_count']}\n⏰ {row['ends_at'].isoformat()}\n"
            f"Статус: {state}", parse_mode="HTML", reply_markup=keyboard,
        )


async def contest_join_callback(callback: CallbackQuery) -> None:
    if not callback.data or not callback.from_user:
        return
    try:
        contest_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Некорректный конкурс.", show_alert=True)
        return
    async with database._require_pool().acquire() as conn:
        async with conn.transaction():
            contest = await conn.fetchrow(
                "SELECT status,ends_at FROM community_contests WHERE id=$1 FOR UPDATE",
                contest_id,
            )
            if not contest or contest["status"] != "open" or contest["ends_at"] <= datetime.now(timezone.utc):
                await callback.answer("Регистрация на этот конкурс завершена.", show_alert=True)
                return
            await conn.execute("""
                INSERT INTO community_contest_entries (contest_id,user_id,display_name)
                VALUES ($1,$2,$3) ON CONFLICT (contest_id,user_id)
                DO UPDATE SET display_name=EXCLUDED.display_name
            """, contest_id, callback.from_user.id, callback.from_user.full_name[:100])
    await callback.answer("Вы участвуете в конкурсе.")


async def draw_contest_command(message: Message) -> None:
    if not _is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Подводить итоги может только владелец проекта.")
        return
    args = (message.text or "").split()
    if len(args) != 2 or not args[1].isdigit():
        await message.answer("Формат: /contestdraw ID")
        return
    contest_id = int(args[1])
    async with database._require_pool().acquire() as conn:
        async with conn.transaction():
            contest = await conn.fetchrow(
                "SELECT * FROM community_contests WHERE id=$1 FOR UPDATE", contest_id
            )
            if not contest or contest["status"] != "open":
                await message.answer("Конкурс не найден или итоги уже подведены.")
                return
            if contest["ends_at"] > datetime.now(timezone.utc):
                await message.answer("Сначала дождитесь даты завершения конкурса.")
                return
            entries = await conn.fetch(
                "SELECT user_id,display_name FROM community_contest_entries WHERE contest_id=$1",
                contest_id,
            )
            if not entries:
                await conn.execute(
                    "UPDATE community_contests SET status='drawn',drawn_at=NOW() WHERE id=$1",
                    contest_id,
                )
                await message.answer("Участников нет. Конкурс закрыт без победителей.")
                return
            winners = secrets.SystemRandom().sample(
                list(entries), min(int(contest["winner_count"]), len(entries))
            )
            for place, winner in enumerate(winners, 1):
                await conn.execute("""
                    INSERT INTO community_contest_winners (contest_id,user_id,place)
                    VALUES ($1,$2,$3)
                """, contest_id, winner["user_id"], place)
                await _add_points(conn, int(winner["user_id"]), 100, f"Победа в конкурсе #{contest_id}")
            await conn.execute(
                "UPDATE community_contests SET status='drawn',drawn_at=NOW() WHERE id=$1",
                contest_id,
            )
    winner_lines = [
        f"{place}. {escape(winner['display_name'] or str(winner['user_id']))} "
        f"(<code>{winner['user_id']}</code>)"
        for place, winner in enumerate(winners, 1)
    ]
    await message.answer(
        f"🏆 <b>Итоги конкурса #{contest_id}</b>\n"
        f"<b>{escape(contest['title'])}</b>\n🎁 {escape(contest['prize'])}\n\n"
        + "\n".join(winner_lines)
        + "\n\nПобедители сохранены в журнале. Выдачу описанного приза подтверждает владелец.",
        parse_mode="HTML",
    )


async def create_promo_command(message: Message) -> None:
    if not _is_owner(message.from_user.id if message.from_user else None):
        await message.answer("⛔ Создавать промокоды может только владелец.")
        return
    args = (message.text or "").split()
    if len(args) != 4:
        await message.answer("Формат: /promocreate КОД БАЛЛЫ КОЛИЧЕСТВО_АКТИВАЦИЙ")
        return
    try:
        code = normalize_promo_code(args[1])
        points, uses = int(args[2]), int(args[3])
        if not 1 <= points <= 10000 or not 1 <= uses <= 100000:
            raise ValueError
    except ValueError:
        await message.answer("Проверь код, баллы (1–10000) и число активаций (1–100000).")
        return
    async with database._require_pool().acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO community_promo_codes (code,points,max_uses,created_by)
                VALUES ($1,$2,$3,$4)
            """, code, points, uses, message.from_user.id)
        except Exception:
            await message.answer("Такой промокод уже существует.")
            return
    await message.answer(f"✅ Промокод <code>{escape(code)}</code> создан: {points} баллов, активаций: {uses}.", parse_mode="HTML")


async def redeem_promo_command(message: Message) -> None:
    if not message.from_user:
        return
    args = (message.text or "").split(maxsplit=1)
    if len(args) != 2:
        await message.answer("Формат: /promo КОД")
        return
    try:
        code = normalize_promo_code(args[1])
    except ValueError as exc:
        await message.answer(escape(str(exc)))
        return
    async with database._require_pool().acquire() as conn:
        async with conn.transaction():
            promo = await conn.fetchrow(
                "SELECT points,max_uses,uses,active FROM community_promo_codes WHERE code=$1 FOR UPDATE",
                code,
            )
            if not promo or not promo["active"] or promo["uses"] >= promo["max_uses"]:
                await message.answer("Промокод недействителен или лимит активаций исчерпан.")
                return
            inserted = await conn.fetchval("""
                INSERT INTO community_promo_redemptions (code,user_id)
                VALUES ($1,$2) ON CONFLICT DO NOTHING RETURNING user_id
            """, code, message.from_user.id)
            if not inserted:
                await message.answer("Вы уже активировали этот промокод.")
                return
            await conn.execute("UPDATE community_promo_codes SET uses=uses+1 WHERE code=$1", code)
            await _add_points(conn, message.from_user.id, int(promo["points"]), f"Промокод {code}")
    await message.answer(f"🎁 Начислено {promo['points']} баллов. Посмотреть баланс: /points")


async def daily_command(message: Message) -> None:
    if not message.from_user:
        return
    async with database._require_pool().acquire() as conn:
        async with conn.transaction():
            claimed = await conn.fetchval("""
                INSERT INTO community_daily_claims (user_id,claim_date,points)
                VALUES ($1,(NOW() AT TIME ZONE 'UTC')::date,25)
                ON CONFLICT DO NOTHING RETURNING user_id
            """, message.from_user.id)
            if not claimed:
                await message.answer("🎁 Ежедневная награда уже получена. Попробуйте завтра.")
                return
            await _add_points(conn, message.from_user.id, 25, "Ежедневная награда")
            balance = await conn.fetchval("SELECT points FROM community_points WHERE user_id=$1", message.from_user.id)
    await message.answer(f"🎁 Получено 25 баллов. Баланс: {balance}.")


async def points_command(message: Message) -> None:
    if not message.from_user:
        return
    async with database._require_pool().acquire() as conn:
        balance = await conn.fetchval("SELECT points FROM community_points WHERE user_id=$1", message.from_user.id)
        balance = int(balance or 0)
    await message.answer(f"⭐ Ваш баланс: <b>{balance}</b> баллов.\nБаллы не имеют денежной стоимости и не обмениваются на деньги или Stars.", parse_mode="HTML")


async def leaderboard_command(message: Message) -> None:
    async with database._require_pool().acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.user_id,p.points,COALESCE(a.display_name,'') AS display_name
            FROM community_points p
            LEFT JOIN (SELECT DISTINCT ON (user_id) user_id,display_name
                       FROM community_contest_entries ORDER BY user_id,joined_at DESC) a
              ON a.user_id=p.user_id
            ORDER BY p.points DESC,p.user_id LIMIT 10
        """)
    if not rows:
        await message.answer("🏆 Рейтинг пока пуст.")
        return
    lines = [
        f"{i}. {escape(row['display_name'] or str(row['user_id']))} — {row['points']} баллов"
        for i, row in enumerate(rows, 1)
    ]
    await message.answer("🏆 <b>Рейтинг сообщества</b>\n\n" + "\n".join(lines), parse_mode="HTML")


async def achievements_command(message: Message) -> None:
    if not message.from_user:
        return
    async with database._require_pool().acquire() as conn:
        rows = await conn.fetch(
            "SELECT achievement_key,awarded_at FROM community_achievements WHERE user_id=$1 ORDER BY awarded_at",
            message.from_user.id,
        )
        balance = await conn.fetchval("SELECT points FROM community_points WHERE user_id=$1", message.from_user.id)
    earned = {str(row["achievement_key"]): row["awarded_at"] for row in rows}
    lines = []
    for threshold, title, description in ACHIEVEMENTS:
        marker = "🏅" if str(threshold) in earned else "🔒"
        lines.append(f"{marker} <b>{title}</b> — {description}")
    await message.answer(
        "🏅 <b>Мои достижения</b>\n\n" + "\n".join(lines)
        + f"\n\nБаланс: {int(balance or 0)} баллов.",
        parse_mode="HTML",
    )


def register_community_rewards_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.message.register(create_contest_command, Command("contestcreate"))
    dispatcher.message.register(list_contests_command, Command("contests"))
    dispatcher.message.register(draw_contest_command, Command("contestdraw"))
    dispatcher.message.register(create_promo_command, Command("promocreate"))
    dispatcher.message.register(redeem_promo_command, Command("promo"))
    dispatcher.message.register(daily_command, Command("daily"))
    dispatcher.message.register(points_command, Command("points"))
    dispatcher.message.register(leaderboard_command, Command("leaderboard"))
    dispatcher.message.register(achievements_command, Command("achievements"))
    dispatcher.callback_query.register(contest_join_callback, F.data.startswith("contest:join:"))
