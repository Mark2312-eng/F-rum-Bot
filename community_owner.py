"""Owner-only Telegram controls for community contests and promo codes."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from html import escape

from aiogram import Dispatcher, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database
from community_rewards import normalize_promo_code, parse_contest_input

_PENDING: dict[int, str] = {}


def _owner(user_id: int | None) -> bool:
    try:
        configured = int(os.getenv("OWNER_TELEGRAM_ID", "0"))
    except ValueError:
        configured = 0
    return bool(user_id and configured > 0 and user_id == configured)


def _menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎉 Конкурсы", callback_data="owner:community:contests")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="owner:community:promos")],
        [InlineKeyboardButton(text="➕ Создать конкурс", callback_data="owner:community:createcontest")],
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="owner:community:createpromo")],
        [InlineKeyboardButton(text="⬅️ Панель владельца", callback_data="owner_panel")],
    ])


async def _show_contests(message: Message) -> None:
    rows = await database._require_pool().fetch("""
        SELECT c.id,c.chat_id,c.title,c.prize,c.ends_at,c.status,c.winner_count,
               COUNT(e.user_id)::int AS entries
        FROM community_contests c
        LEFT JOIN community_contest_entries e ON e.contest_id=c.id
        WHERE c.status <> 'cancelled'
        GROUP BY c.id ORDER BY c.created_at DESC LIMIT 10
    """)
    if not rows:
        await message.answer("🎉 Конкурсов пока нет.", reply_markup=_menu())
        return
    await message.answer("🎉 <b>Последние конкурсы</b>", parse_mode="HTML")
    for row in rows:
        status = "🟢 Регистрация открыта" if row["status"] == "open" and row["ends_at"] > datetime.now(timezone.utc) else ("🏁 Итоги подведены" if row["status"] == "drawn" else "⌛ Срок регистрации истёк")
        body = (
            f"<b>#{row['id']} · {escape(row['title'])}</b>\n🎁 {escape(row['prize'])}\n"
            f"👥 Участников: {row['entries']} · Победителей: {row['winner_count']}\n"
            f"🗨 Чат: <code>{row['chat_id']}</code>\n⏰ {row['ends_at'].isoformat()}\n{status}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Закрыть конкурс", callback_data=f"owner:community:cancel:{row['id']}")
        ]]) if row["status"] == "open" else None
        await message.answer(body, parse_mode="HTML", reply_markup=keyboard)
    await message.answer("Управление конкурсами:", reply_markup=_menu())


async def _show_promos(message: Message) -> None:
    rows = await database._require_pool().fetch("""
        SELECT code,points,max_uses,uses,active
        FROM community_promo_codes ORDER BY created_at DESC LIMIT 20
    """)
    if not rows:
        await message.answer("🎟 Промокодов пока нет.", reply_markup=_menu())
        return
    for row in rows:
        status = "активен" if row["active"] and row["uses"] < row["max_uses"] else "неактивен"
        body = f"🎟 <code>{escape(row['code'])}</code> — {row['points']} баллов\nИспользовано: {row['uses']}/{row['max_uses']} · {status}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Отключить", callback_data=f"owner:community:deactivate:{row['code']}")
        ]]) if row["active"] and row["uses"] < row["max_uses"] else None
        await message.answer(body, parse_mode="HTML", reply_markup=keyboard)
    await message.answer("Управление промокодами:", reply_markup=_menu())


async def community_owner_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not _owner(callback.from_user.id):
        await callback.answer("Доступ только владельцу.", show_alert=True)
        return
    if not callback.message or callback.message.chat.type != "private":
        await callback.answer("Откройте управление в личном чате с ботом.", show_alert=True)
        return
    await callback.answer()
    action = (callback.data or "").split(":")
    operation = action[2] if len(action) >= 3 else ""
    if operation == "contests":
        await _show_contests(callback.message)
    elif operation == "promos":
        await _show_promos(callback.message)
    elif operation == "createcontest":
        _PENDING[callback.from_user.id] = "contest"
        await callback.message.answer(
            "Отправьте: <code>CHAT_ID | название | 2026-12-20T18:00+03:00 | победителей | приз</code>\n"
            "CHAT_ID — ID группы для публикации. Участие бесплатное.\nОтмена: /cancel",
            parse_mode="HTML",
        )
    elif operation == "createpromo":
        _PENDING[callback.from_user.id] = "promo"
        await callback.message.answer("Отправьте: <code>КОД | БАЛЛЫ | ЛИМИТ_АКТИВАЦИЙ</code>\nОтмена: /cancel", parse_mode="HTML")
    elif operation == "cancel" and len(action) == 4 and action[3].isdigit():
        result = await database._require_pool().execute(
            "UPDATE community_contests SET status='cancelled' WHERE id=$1 AND status='open'", int(action[3])
        )
        await callback.message.answer("Конкурс закрыт." if result.endswith(" 1") else "Конкурс уже закрыт или не найден.", reply_markup=_menu())
    elif operation == "deactivate" and len(action) == 4:
        try:
            code = normalize_promo_code(action[3])
        except ValueError:
            await callback.message.answer("Некорректный промокод.", reply_markup=_menu())
            return
        result = await database._require_pool().execute(
            "UPDATE community_promo_codes SET active=FALSE WHERE code=$1 AND active=TRUE", code
        )
        await callback.message.answer("Промокод отключён." if result.endswith(" 1") else "Промокод уже отключён или не найден.", reply_markup=_menu())


async def _pending_message(message: Message) -> None:
    if not message.from_user or not _owner(message.from_user.id):
        return
    mode = _PENDING.pop(message.from_user.id, None)
    if not mode:
        return
    raw = (message.text or "").strip()
    if raw.lower() == "/cancel":
        await message.answer("Действие отменено.", reply_markup=_menu())
        return
    try:
        if mode == "contest":
            parts = [part.strip() for part in raw.split("|", 1)]
            if len(parts) != 2 or not parts[0].lstrip("-").isdigit():
                raise ValueError("Укажите CHAT_ID, затем | и данные конкурса.")
            chat_id = int(parts[0])
            title, ends_at, winners, prize = parse_contest_input(parts[1])
            async with database._require_pool().acquire() as conn:
                contest_id = await conn.fetchval("""
                    INSERT INTO community_contests (chat_id,created_by,title,prize,ends_at,winner_count)
                    VALUES ($1,$2,$3,$4,$5,$6) RETURNING id
                """, chat_id, message.from_user.id, title, prize, ends_at, winners)
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🎉 Участвовать", callback_data=f"contest:join:{contest_id}")
            ]])
            await message.bot.send_message(
                chat_id,
                f"🎉 <b>КОНКУРС #{contest_id}</b>\n\n<b>{escape(title)}</b>\n🎁 Приз: {escape(prize)}\n"
                f"🏆 Победителей: {winners}\n⏰ Завершение: {ends_at.isoformat()}\n\nУчастие бесплатное.",
                parse_mode="HTML", reply_markup=keyboard,
            )
            await message.answer(f"✅ Конкурс #{contest_id} создан и опубликован.", reply_markup=_menu())
        else:
            parts = [part.strip() for part in raw.split("|")]
            if len(parts) != 3:
                raise ValueError("Формат: КОД | БАЛЛЫ | ЛИМИТ_АКТИВАЦИЙ")
            code = normalize_promo_code(parts[0])
            points, limit = int(parts[1]), int(parts[2])
            if not 1 <= points <= 10000 or not 1 <= limit <= 100000:
                raise ValueError("Баллы: 1–10000, лимит активаций: 1–100000.")
            await database._require_pool().execute(
                "INSERT INTO community_promo_codes (code,points,max_uses,created_by) VALUES ($1,$2,$3,$4)",
                code, points, limit, message.from_user.id,
            )
            await message.answer(f"✅ Промокод <code>{escape(code)}</code> создан.", parse_mode="HTML", reply_markup=_menu())
    except Exception as exc:
        _PENDING[message.from_user.id] = mode
        await message.answer(f"⚠️ {escape(str(exc)[:300])}\nПопробуйте ещё раз или отправьте /cancel.")


def register_community_owner_handlers(dispatcher: Dispatcher) -> None:
    dispatcher.callback_query.register(community_owner_callback, F.data.startswith("owner:community:"))
    dispatcher.message.register(_pending_message, F.text, lambda message: bool(message.from_user and message.from_user.id in _PENDING))
