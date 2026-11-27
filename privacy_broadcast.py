"""Privacy consent and owner-only Telegram broadcast features."""

import asyncio
import logging
import os
from datetime import datetime, timezone

import asyncpg
from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from database import database

LOGGER = logging.getLogger(__name__)
CONSENT_VERSION = "2026-11-27"
PUBLIC_SITE = os.getenv("PUBLIC_SITE_ORIGIN", "https://f-rum-bot-info.onrender.com").rstrip("/")
PRIVACY_URL = f"{PUBLIC_SITE}/privacy.html"
PERSONAL_DATA_URL = f"{PUBLIC_SITE}/personal-data.html"
_PENDING_BROADCASTS: dict[int, tuple[int, int]] = {}
_ACTIVE_BROADCASTS: set[int] = set()


def _owner_id() -> int:
    try:
        return int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    except ValueError:
        return 0


async def ensure_privacy_schema() -> None:
    """Create consent and broadcast tables and record the migration."""
    pool = database._require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS bot_user_consents (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    first_name TEXT NOT NULL DEFAULT '',
                    consent_version TEXT NOT NULL,
                    accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS bot_broadcast_subscriptions (
                    user_id BIGINT PRIMARY KEY
                        REFERENCES bot_user_consents(user_id) ON DELETE CASCADE,
                    subscribed BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS bot_broadcast_subscriptions_active_idx
                    ON bot_broadcast_subscriptions (user_id)
                    WHERE subscribed = TRUE;
                CREATE TABLE IF NOT EXISTS bot_broadcast_history (
                    id BIGSERIAL PRIMARY KEY,
                    created_by BIGINT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('sending', 'completed', 'cancelled')),
                    sent_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                );
                INSERT INTO schema_migrations (version, description)
                VALUES ('0003_privacy_consent_broadcast',
                        'Explicit user consent, optional broadcast subscriptions and broadcast history')
                ON CONFLICT (version) DO NOTHING;
            """)


async def has_consent(user_id: int) -> bool:
    pool = database._require_pool()
    return bool(await pool.fetchval(
        "SELECT EXISTS(SELECT 1 FROM bot_user_consents WHERE user_id = $1)",
        user_id,
    ))


async def has_subscription_choice(user_id: int) -> bool:
    pool = database._require_pool()
    return bool(await pool.fetchval(
        "SELECT EXISTS(SELECT 1 FROM bot_broadcast_subscriptions WHERE user_id = $1)",
        user_id,
    ))


def consent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Политика конфиденциальности", url=PRIVACY_URL)],
        [InlineKeyboardButton(text="📑 Обработка персональных данных", url=PERSONAL_DATA_URL)],
        [InlineKeyboardButton(text="✅ Принимаю и продолжить", callback_data="consent:accept")],
        [InlineKeyboardButton(text="❌ Отказаться", callback_data="consent:decline")],
    ])


def subscription_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Подписаться на обновления", callback_data="subscription:yes")],
        [InlineKeyboardButton(text="Не получать уведомления", callback_data="subscription:no")],
    ])


async def show_consent_prompt(message: Message) -> None:
    await message.answer(
        "👋 <b>Добро пожаловать в VISE RUSSIA!</b>\n\n"
        "Перед началом работы ознакомьтесь с документами о конфиденциальности "
        "и обработке данных. Для продолжения необходимо подтвердить согласие.\n\n"
        "Бот сохраняет Telegram ID, имя пользователя (если указано), дату и версию согласия. "
        "Эти данные используются для работы функций бота и учёта вашего выбора.\n\n"
        "Подписка на информационные рассылки будет предложена отдельно и остаётся добровольной.",
        parse_mode="HTML",
        reply_markup=consent_keyboard(),
        disable_web_page_preview=True,
    )


async def show_subscription_prompt(message: Message) -> None:
    await message.answer(
        "✅ Согласие сохранено.\n\n"
        "Хотите отдельно подписаться на новости и обновления VISE RUSSIA? "
        "Это необязательно. Отписаться можно командой /stop.",
        reply_markup=subscription_keyboard(),
    )


async def consent_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    user = callback.from_user
    pool = database._require_pool()
    await callback.answer()
    if data == "consent:decline":
        if callback.message:
            await callback.message.answer(
                "Вы отказались от согласия. Функции бота останутся недоступны. "
                "Если передумаете, отправьте /start."
            )
        return
    if data != "consent:accept":
        return
    await pool.execute(
        """INSERT INTO bot_user_consents (user_id, username, first_name, consent_version)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id) DO UPDATE SET
             username = EXCLUDED.username,
             first_name = EXCLUDED.first_name,
             consent_version = EXCLUDED.consent_version,
             accepted_at = NOW()""",
        user.id, user.username, user.first_name or "", CONSENT_VERSION,
    )
    await pool.execute(
        """INSERT INTO bot_broadcast_subscriptions (user_id, subscribed)
           VALUES ($1, FALSE) ON CONFLICT (user_id) DO NOTHING""",
        user.id,
    )
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await show_subscription_prompt(callback.message)


async def subscription_callback(callback: CallbackQuery) -> None:
    data = callback.data or ""
    user_id = callback.from_user.id
    await callback.answer()
    if not await has_consent(user_id):
        if callback.message:
            await show_consent_prompt(callback.message)
        return
    subscribed = data == "subscription:yes"
    pool = database._require_pool()
    await pool.execute(
        """INSERT INTO bot_broadcast_subscriptions (user_id, subscribed)
           VALUES ($1, $2)
           ON CONFLICT (user_id) DO UPDATE SET
             subscribed = EXCLUDED.subscribed, updated_at = NOW()""",
        user_id, subscribed,
    )
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "🔔 Вы подписались на обновления VISE RUSSIA."
            if subscribed else "Вы не подписаны на рассылку. Настройки можно изменить через /start."
        )


async def stop_broadcasts(message: Message) -> None:
    if not message.from_user:
        return
    pool = database._require_pool()
    await pool.execute(
        """UPDATE bot_broadcast_subscriptions
           SET subscribed = FALSE, updated_at = NOW()
           WHERE user_id = $1""",
        message.from_user.id,
    )
    await message.answer("Вы отписались от информационных рассылок VISE RUSSIA.")


async def withdraw_consent(message: Message) -> None:
    if not message.from_user:
        return
    pool = database._require_pool()
    await pool.execute(
        "DELETE FROM bot_user_consents WHERE user_id = $1",
        message.from_user.id,
    )
    await message.answer(
        "Согласие отозвано, запись о согласии и подписке удалена. "
        "Для повторного использования бота потребуется снова отправить /start."
    )


class ConsentGateMiddleware(BaseMiddleware):
    """Require consent before processing private bot commands or callbacks."""

    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        chat = getattr(event, "chat", None)
        if chat is None and isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat
        is_private = bool(chat and getattr(chat, "type", None) == "private")
        if not is_private or user is None:
            return await handler(event, data)

        text = getattr(event, "text", None) or ""
        callback_data = getattr(event, "data", None) or ""
        allowed_message = text.split(maxsplit=1)[0].split("@", 1)[0] in {
            "/start", "/stop", "/withdraw_consent"
        }
        allowed_callback = callback_data.startswith(("consent:", "subscription:"))
        if allowed_message or allowed_callback:
            return await handler(event, data)
        if not await has_consent(user.id):
            if isinstance(event, Message):
                await show_consent_prompt(event)
            elif isinstance(event, CallbackQuery) and event.message:
                await event.answer()
                await show_consent_prompt(event.message)
            return None
        return await handler(event, data)


async def start_broadcast(message: Message) -> None:
    owner_id = _owner_id()
    if owner_id <= 0 or not message.from_user or message.from_user.id != owner_id:
        await message.answer("⛔ Команда доступна только владельцу бота.")
        return
    if message.chat.type != "private":
        await message.answer("Запускайте рассылку в личном чате с ботом.")
        return
    _PENDING_BROADCASTS.pop(owner_id, None)
    _PENDING_BROADCASTS[owner_id] = (0, 0)
    await message.answer(
        "📨 <b>Создание рассылки</b>\n\n"
        "Отправьте следующим сообщением текст, фото или другой материал. "
        "Я покажу предпросмотр перед отправкой.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="broadcast:cancel")]
        ]),
    )


async def capture_broadcast_content(message: Message) -> None:
    owner_id = _owner_id()
    if not message.from_user or message.from_user.id != owner_id:
        return
    if owner_id not in _PENDING_BROADCASTS:
        return
    if message.text and message.text.strip().lower() in {"/cancel", "отмена"}:
        _PENDING_BROADCASTS.pop(owner_id, None)
        await message.answer("Создание рассылки отменено.")
        return
    _PENDING_BROADCASTS[owner_id] = (message.chat.id, message.message_id)
    await message.bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await message.answer(
        "Проверьте предпросмотр. Отправить сообщение всем пользователям, "
        "которые приняли документы и отдельно подписались на обновления?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Подтвердить рассылку", callback_data="broadcast:confirm")],
            [InlineKeyboardButton(text="✖️ Отмена", callback_data="broadcast:cancel")],
        ]),
    )


async def broadcast_callback(callback: CallbackQuery) -> None:
    owner_id = _owner_id()
    if owner_id <= 0 or callback.from_user.id != owner_id:
        await callback.answer("Недостаточно прав.", show_alert=True)
        return
    data = callback.data or ""
    await callback.answer()
    if data == "broadcast:stop":
        _ACTIVE_BROADCASTS.discard(owner_id)
        if callback.message:
            await callback.message.answer("⏹ Запрошена остановка рассылки.")
        return
    if data == "broadcast:cancel":
        _PENDING_BROADCASTS.pop(owner_id, None)
        if callback.message:
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.answer("Рассылка отменена.")
        return
    if data != "broadcast:confirm":
        return
    source = _PENDING_BROADCASTS.pop(owner_id, None)
    if source is None or source == (0, 0):
        if callback.message:
            await callback.message.answer("Нет подготовленного сообщения. Используйте /broadcast.")
        return
    source_chat_id, source_message_id = source
    pool = database._require_pool()
    recipients = await pool.fetch(
        """SELECT c.user_id FROM bot_user_consents c
           JOIN bot_broadcast_subscriptions s ON s.user_id = c.user_id
           WHERE s.subscribed = TRUE ORDER BY c.user_id"""
    )
    history_id = await pool.fetchval(
        """INSERT INTO bot_broadcast_history (created_by, status)
           VALUES ($1, 'sending') RETURNING id""",
        owner_id,
    )
    sent = failed = 0
    _ACTIVE_BROADCASTS.add(owner_id)
    bot: Bot = callback.bot
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏹ Остановить рассылку", callback_data="broadcast:stop")]
        ]))
    for row in recipients:
        if owner_id not in _ACTIVE_BROADCASTS:
            break
        try:
            await bot.copy_message(
                chat_id=int(row["user_id"]),
                from_chat_id=source_chat_id,
                message_id=source_message_id,
            )
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(min(float(exc.retry_after), 60.0))
            try:
                await bot.copy_message(
                    chat_id=int(row["user_id"]),
                    from_chat_id=source_chat_id,
                    message_id=source_message_id,
                )
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            failed += 1
        await asyncio.sleep(0.05)
    was_cancelled = owner_id not in _ACTIVE_BROADCASTS
    _ACTIVE_BROADCASTS.discard(owner_id)
    await pool.execute(
        """UPDATE bot_broadcast_history SET status = $2,
           sent_count = $3, failed_count = $4, completed_at = NOW()
           WHERE id = $1""",
        history_id, "cancelled" if was_cancelled else "completed", sent, failed,
    )
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            "✅ <b>Рассылка завершена</b>\n"
            f"Успешно отправлено: <b>{sent}</b>\n"
            f"Ошибок: <b>{failed}</b>\n"
            f"Всего получателей: <b>{len(recipients)}</b>\n"
            + ("⏹ Рассылка остановлена владельцем." if was_cancelled else ""),
            parse_mode="HTML",
        )


def register_privacy_broadcast_handlers(dispatcher: Dispatcher) -> None:
    """Register consent, subscription, and owner broadcast handlers."""
    dispatcher.message.outer_middleware(ConsentGateMiddleware())
    dispatcher.callback_query.outer_middleware(ConsentGateMiddleware())
    dispatcher.message.register(stop_broadcasts, Command("stop"))
    dispatcher.message.register(withdraw_consent, Command("withdraw_consent"))
    dispatcher.message.register(start_broadcast, Command("broadcast"))
    dispatcher.message.register(
        capture_broadcast_content,
        lambda message: bool(message.from_user and message.from_user.id == _owner_id()
                             and _owner_id() in _PENDING_BROADCASTS
                             and (message.content_type != "text"
                                  or not (message.text or "").startswith("/")
                                  or (message.text or "").strip().lower() == "/cancel")),
    )
    dispatcher.callback_query.register(consent_callback, F.data.startswith("consent:"))
    dispatcher.callback_query.register(subscription_callback, F.data.startswith("subscription:"))
    dispatcher.callback_query.register(broadcast_callback, F.data.startswith("broadcast:"))
