"""Owner-only VIP membership operations inside the Telegram bot panel."""

import logging
import os
import time

from aiogram import Dispatcher, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database
from vip_stars import TIERS

LOGGER = logging.getLogger(__name__)
_PENDING: dict[tuple[int, int], tuple[str, float]] = {}
_PENDING_TTL = 300


def parse_grant_input(value: str) -> tuple[int, str, int] | None:
    """Parse '<telegram_id> <tier> <days>' with strict bounds."""
    parts = value.split()
    if len(parts) != 3 or not parts[0].isdigit() or not parts[2].isdigit():
        return None
    user_id, tier, days = int(parts[0]), parts[1].lower(), int(parts[2])
    if not 1 <= user_id <= 9_223_372_036_854_775_807:
        return None
    if tier not in TIERS or not 1 <= days <= 3650:
        return None
    return user_id, tier, days


def _owner_id() -> int:
    try:
        return int(os.getenv("OWNER_TELEGRAM_ID", "0") or "0")
    except ValueError:
        return 0


def _is_owner_private(user_id: int, chat_type: str) -> bool:
    owner_id = _owner_id()
    return owner_id > 0 and user_id == owner_id and chat_type == "private"


async def ensure_vip_admin_schema() -> None:
    pool = database._require_pool()
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS bot_vip_admin_audit (
            id BIGSERIAL PRIMARY KEY,
            actor_user_id BIGINT NOT NULL,
            target_user_id BIGINT NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('grant', 'revoke')),
            tier TEXT CHECK (tier IN ('silver', 'gold', 'diamond')),
            days INTEGER CHECK (days BETWEEN 1 AND 3650),
            previous_expires_at TIMESTAMPTZ,
            new_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS bot_vip_admin_audit_created_idx
            ON bot_vip_admin_audit (created_at DESC);
    """)


def _set_pending(chat_id: int, user_id: int, action: str) -> None:
    now = time.monotonic()
    for key, (_action, expiry) in list(_PENDING.items()):
        if expiry <= now:
            _PENDING.pop(key, None)
    _PENDING[(chat_id, user_id)] = (action, now + _PENDING_TTL)


def _pop_pending(chat_id: int, user_id: int) -> str | None:
    item = _PENDING.pop((chat_id, user_id), None)
    if item is None or item[1] <= time.monotonic():
        return None
    return item[0]


async def _show_vip_menu(message: Message) -> None:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Активные VIP", callback_data="owner:vip:buyers")],
        [InlineKeyboardButton(text="🧾 История платежей", callback_data="owner:vip:sales")],
        [InlineKeyboardButton(text="➕ Выдать / продлить VIP", callback_data="owner:vipadmin:grant")],
        [InlineKeyboardButton(text="➖ Снять VIP", callback_data="owner:vipadmin:revoke")],
        [InlineKeyboardButton(text="📋 Журнал действий", callback_data="owner:vipadmin:audit")],
        [InlineKeyboardButton(text="⬅️ Панель владельца", callback_data="owner_panel")],
    ])
    await message.answer("💎 <b>Управление VIP</b>\nВыберите действие:", parse_mode="HTML", reply_markup=keyboard)


async def _handle_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None or not _is_owner_private(callback.from_user.id, message.chat.type):
        await callback.answer("⛔ Доступ только владельцу в личном чате.", show_alert=True)
        return
    data = callback.data or ""
    action = data.removeprefix("owner:vipadmin:")
    if action == "grant":
        _set_pending(message.chat.id, callback.from_user.id, "grant")
        await message.answer(
            "Отправьте одной строкой: <code>TELEGRAM_ID silver|gold|diamond ДНИ</code>\n"
            "Например: <code>123456789 gold 30</code>. Максимальный срок — 3650 дней.",
            parse_mode="HTML",
        )
    elif action == "revoke":
        _set_pending(message.chat.id, callback.from_user.id, "revoke")
        await message.answer("Отправьте Telegram ID пользователя, у которого нужно снять VIP.")
    elif action.startswith("revoke_confirm:"):
        parts = action.split(":")
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            await callback.answer("Некорректное подтверждение.", show_alert=True)
            return
        target_id, expected_expiry_us = int(parts[1]), int(parts[2])
        pool = database._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                previous = await connection.fetchrow(
                    """SELECT tier, expires_at FROM bot_vip_memberships
                       WHERE user_id = $1 AND expires_at > NOW() FOR UPDATE""",
                    target_id,
                )
                if previous is None:
                    await callback.answer("Активная VIP-запись уже отсутствует.", show_alert=True)
                    return
                current_expiry_us = int(previous["expires_at"].timestamp() * 1_000_000)
                if current_expiry_us != expected_expiry_us:
                    await callback.answer("Подтверждение устарело. Запросите снятие заново.", show_alert=True)
                    return
                await connection.execute(
                    "DELETE FROM bot_vip_memberships WHERE user_id = $1 AND expires_at = $2",
                    target_id, previous["expires_at"],
                )
                await connection.execute(
                    """INSERT INTO bot_vip_admin_audit
                       (actor_user_id, target_user_id, action, tier, previous_expires_at)
                       VALUES ($1, $2, 'revoke', $3, $4)""",
                    callback.from_user.id, target_id, previous["tier"], previous["expires_at"],
                )
        await callback.answer("VIP снят.")
        await message.answer(f"✅ VIP снят у пользователя <code>{target_id}</code>.", parse_mode="HTML")
        try:
            await callback.bot.send_message(target_id, "Ваш VIP-статус был отключён владельцем проекта.")
        except Exception:
            LOGGER.info("Could not notify user %s about VIP revocation", target_id)
    elif action == "audit":
        pool = database._require_pool()
        rows = await pool.fetch(
            """SELECT actor_user_id, target_user_id, action, tier, days,
                      previous_expires_at, new_expires_at, created_at
               FROM bot_vip_admin_audit
               ORDER BY id DESC LIMIT 20"""
        )
        lines = ["📋 <b>Журнал ручного управления VIP</b>", ""]
        for row in rows:
            tier = TIERS.get(str(row["tier"]), {})
            tier_name = tier.get("name", str(row["tier"] or "—"))
            verb = "выдал / продлил" if row["action"] == "grant" else "снял"
            created = row["created_at"].strftime("%d.%m.%Y %H:%M UTC")
            detail = tier_name
            if row["days"]:
                detail += f", +{int(row['days'])} дн."
            if row["new_expires_at"]:
                detail += f", до {row['new_expires_at'].strftime('%d.%m.%Y')}"
            elif row["previous_expires_at"]:
                detail += f", прежний срок до {row['previous_expires_at'].strftime('%d.%m.%Y')}"
            lines.append(
                f"• <code>{int(row['actor_user_id'])}</code> {verb} "
                f"<code>{int(row['target_user_id'])}</code> — {detail}\n"
                f"  <i>{created}</i>"
            )
        if not rows:
            lines.append("Ручных изменений пока нет.")
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ К VIP-магазину", callback_data="owner:vip")],
            [InlineKeyboardButton(text="⬅️ Панель владельца", callback_data="owner_panel")],
        ])
        await callback.answer()
        await message.answer("\\n".join(lines), parse_mode="HTML", reply_markup=keyboard)
    elif action == "cancel":
        _PENDING.pop((message.chat.id, callback.from_user.id), None)
        await callback.answer("Отменено.")
        await message.answer("Действие отменено.")
    else:
        await callback.answer("Неизвестное действие.", show_alert=True)


async def _handle_input(message: Message) -> None:
    if not message.from_user or not message.text or message.chat.type != "private":
        return
    if not _is_owner_private(message.from_user.id, message.chat.type):
        return
    action = _pop_pending(message.chat.id, message.from_user.id)
    if action == "grant":
        parsed = parse_grant_input(message.text.strip())
        if parsed is None:
            await message.answer(
                "Формат неверный. Отправьте: <code>TELEGRAM_ID silver|gold|diamond ДНИ</code>.",
                parse_mode="HTML",
            )
            return
        target_id, tier, days = parsed
        pool = database._require_pool()
        async with pool.acquire() as connection:
            async with connection.transaction():
                previous = await connection.fetchval(
                    "SELECT expires_at FROM bot_vip_memberships WHERE user_id = $1 FOR UPDATE",
                    target_id,
                )
                row = await connection.fetchrow(
                    """INSERT INTO bot_vip_memberships (user_id, tier, expires_at)
                       VALUES ($1, $2, NOW() + ($3 * INTERVAL '1 day'))
                       ON CONFLICT (user_id) DO UPDATE SET
                         tier = EXCLUDED.tier,
                         expires_at = GREATEST(bot_vip_memberships.expires_at, NOW())
                                      + ($3 * INTERVAL '1 day'),
                         updated_at = NOW()
                       RETURNING expires_at""",
                    target_id, tier, days,
                )
                await connection.execute(
                    """INSERT INTO bot_vip_admin_audit
                       (actor_user_id, target_user_id, action, tier, days,
                        previous_expires_at, new_expires_at)
                       VALUES ($1, $2, 'grant', $3, $4, $5, $6)""",
                    message.from_user.id, target_id, tier, days, previous, row["expires_at"],
                )
        expiry = row["expires_at"].strftime("%d.%m.%Y %H:%M UTC")
        await message.answer(
            f"✅ Выдан / продлён {TIERS[tier]['badge']} <b>{TIERS[tier]['name']}</b>\n"
            f"Пользователь: <code>{target_id}</code>\n"
            f"Добавлено дней: <b>{days}</b>\nСрок до: <b>{expiry}</b>",
            parse_mode="HTML",
        )
        try:
            await message.bot.send_message(
                target_id,
                f"🎉 Вам выдан / продлён {TIERS[tier]['badge']} {TIERS[tier]['name']} до {expiry}.",
            )
        except Exception:
            LOGGER.info("Could not notify user %s about VIP grant", target_id)
    elif action == "revoke":
        raw_id = message.text.strip()
        if not raw_id.isdigit() or not 1 <= int(raw_id) <= 9_223_372_036_854_775_807:
            await message.answer("Укажите корректный числовой Telegram ID.")
            return
        target_id = int(raw_id)
        pool = database._require_pool()
        membership = await pool.fetchrow(
            "SELECT tier, expires_at FROM bot_vip_memberships WHERE user_id = $1 AND expires_at > NOW()",
            target_id,
        )
        if membership is None:
            await message.answer("У пользователя нет активного VIP.")
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚠️ Подтвердить снятие", callback_data=f"owner:vipadmin:revoke_confirm:{target_id}:{int(membership['expires_at'].timestamp() * 1_000_000)}")],
            [InlineKeyboardButton(text="Отмена", callback_data="owner:vipadmin:cancel")],
        ])
        await message.answer(
            f"Снять {TIERS[str(membership['tier'])]['name']} у пользователя "
            f"<code>{target_id}</code>?\nСрок сейчас до: "
            f"<b>{membership['expires_at'].strftime('%d.%m.%Y %H:%M UTC')}</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )


def register_vip_admin_handlers(dispatcher: Dispatcher) -> None:
    """Register owner-only VIP grant/revoke controls before catch-all handlers."""
    dispatcher.callback_query.register(_handle_callback, F.data.startswith("owner:vipadmin:"))
    dispatcher.message.register(
        _handle_input,
        lambda message: bool(message.from_user and message.chat.type == "private"
                             and (message.chat.id, message.from_user.id) in _PENDING),
    )
