"""One-time VIP memberships paid with Telegram Stars."""

import logging
import os
import uuid
from datetime import timezone
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from database import database

LOGGER = logging.getLogger(__name__)
TIERS = {
    "silver": {
        "name": "VIP Silver",
        "badge": "🥈",
        "perks": ("VIP-бейдж в карточке участника", "Команды /vipprofile и /vipbadge"),
    },
    "gold": {
        "name": "VIP Gold",
        "badge": "🥇",
        "perks": (
            "Все возможности Silver",
            "Персональное отображаемое имя через /vipname",
        ),
    },
    "diamond": {
        "name": "VIP Diamond",
        "badge": "💎",
        "perks": (
            "Все возможности Gold",
            "Персональный титул в карточке через /viptitle",
        ),
    },
}
TIER_ORDER = {"silver": 1, "gold": 2, "diamond": 3}
PRICE_ENV = {
    "silver": "VIP_SILVER_PRICE_STARS",
    "gold": "VIP_GOLD_PRICE_STARS",
    "diamond": "VIP_DIAMOND_PRICE_STARS",
}


def tier_price(tier: str) -> int | None:
    """Return a valid configured Stars price; an unset price disables checkout."""
    env_name = PRICE_ENV.get(tier)
    if not env_name:
        return None
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    try:
        amount = int(raw)
    except ValueError:
        LOGGER.error("Invalid VIP Stars price configuration: %s", env_name)
        return None
    if not 1 <= amount <= 10000:
        LOGGER.error("VIP Stars price is outside Telegram's supported range: %s", env_name)
        return None
    return amount


def vip_shop_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for tier, details in TIERS.items():
        price = tier_price(tier)
        price_text = f"{price} ⭐" if price is not None else "Скоро"
        rows.append([InlineKeyboardButton(
            text=f"{details['badge']} {details['name']} · {price_text}",
            callback_data=f"vip:detail:{tier}",
        )])
    rows.extend([
        [InlineKeyboardButton(text="📊 Сравнить тарифы", callback_data="vip:page:compare")],
        [InlineKeyboardButton(text="👤 Мой VIP", callback_data="vip:page:status"),
         InlineKeyboardButton(text="❔ Помощь", callback_data="vip:page:faq")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_shop_text() -> str:
    lines = [
        "⭐ <b>VIP-магазин VISE RUSSIA</b>",
        "<i>Дополнительные возможности оформления профиля.</i>",
        "",
        "Выберите тариф, чтобы посмотреть его привилегии.",
        "",
    ]
    for tier, details in TIERS.items():
        price = tier_price(tier)
        price_text = f"{price} ⭐" if price is not None else "временно недоступен"
        lines.append(f"{details['badge']} <b>{details['name']}</b> · {price_text}")
    lines.extend([
        "",
        "⏳ Каждый тариф действует 30 дней. Без автопродления.",
        "VIP не даёт прав модерации или администрирования.",
    ])
    return "\n".join(lines)


def _detail_text(tier: str) -> str:
    details = TIERS[tier]
    price = tier_price(tier)
    price_text = f"{price} ⭐" if price is not None else "Пока недоступен"
    perks = "\n".join(f"• {escape(perk)}" for perk in details["perks"])
    return (
        f"{details['badge']} <b>{escape(details['name'])}</b>\n"
        f"<b>Стоимость:</b> {price_text}\n"
        "<b>Срок:</b> 30 дней, единоразовая оплата\n\n"
        "<b>Привилегии:</b>\n" + perks + "\n\n"
        "Автопродления нет. VIP не повышает роль и не открывает команды модерации."
    )


def _detail_keyboard(tier: str) -> InlineKeyboardMarkup:
    price = tier_price(tier)
    button = InlineKeyboardButton(
        text=f"⭐ Купить за {price} Stars" if price is not None else "Покупка недоступна",
        callback_data=f"vip:confirm:{tier}" if price is not None else "vip:page:faq",
    )
    return InlineKeyboardMarkup(inline_keyboard=[
        [button],
        [InlineKeyboardButton(text="⬅️ В магазин", callback_data="vip:page:shop")],
    ])


def _compare_text() -> str:
    return (
        "📊 <b>Сравнение VIP-уровней</b>\n\n"
        "🥈 <b>Silver · 25 ⭐</b>\n"
        "• VIP-бейдж\n• /vipprofile и /vipbadge\n\n"
        "🥇 <b>Gold · 50 ⭐</b>\n"
        "• Всё из Silver\n• Персональное имя: /vipname\n\n"
        "💎 <b>Diamond · 100 ⭐</b>\n"
        "• Всё из Gold\n• Персональный титул: /viptitle\n\n"
        "Все тарифы действуют 30 дней без автопродления."
    )


def _faq_text() -> str:
    return (
        "❔ <b>Помощь по VIP</b>\n\n"
        "• Оплата проходит через Telegram Stars.\n"
        "• Подписка действует 30 дней с момента оплаты.\n"
        "• Автопродления и регулярных списаний нет.\n"
        "• Продление оформляется вручную новой покупкой.\n"
        "• VIP не даёт административных или модераторских прав.\n\n"
        "По вопросам платежа: /paysupport."
    )


def _navigation_keyboard(page: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Магазин", callback_data="vip:page:shop")],
        [InlineKeyboardButton(text="📊 Сравнить тарифы", callback_data="vip:page:compare")],
        [InlineKeyboardButton(text="👤 Мой VIP", callback_data="vip:page:status")],
    ])


async def _status_screen(user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    membership = await _active_membership(user_id)
    if membership is None:
        body = "👤 <b>Мой VIP</b>\n\nАктивной подписки нет. Выберите тариф в магазине."
    else:
        tier = str(membership["tier"])
        expiry = membership["expires_at"].astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
        body = (
            f"👤 <b>Мой VIP</b>\n\n{TIERS[tier]['badge']} "
            f"<b>{escape(TIERS[tier]['name'])}</b>\n"
            f"Действует до: <b>{expiry}</b>\nАвтопродления нет."
        )
    return body, _navigation_keyboard("status")


async def _edit_vip_screen(callback: CallbackQuery, text: str,
                           keyboard: InlineKeyboardMarkup) -> None:
    if callback.message:
        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await callback.answer()


async def ensure_vip_schema() -> None:
    """Create the VIP purchase ledger and active membership tables."""
    pool = database._require_pool()
    async with pool.acquire() as connection:
        async with connection.transaction():
            await connection.execute("""
                CREATE TABLE IF NOT EXISTS bot_vip_invoice_intents (
                    payload TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    tier TEXT NOT NULL CHECK (tier IN ('silver', 'gold', 'diamond')),
                    amount INTEGER NOT NULL CHECK (amount BETWEEN 1 AND 10000),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'paid')),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bot_vip_invoice_intents_user_idx
                    ON bot_vip_invoice_intents (user_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS bot_vip_payments (
                    telegram_charge_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL UNIQUE
                        REFERENCES bot_vip_invoice_intents(payload),
                    user_id BIGINT NOT NULL,
                    tier TEXT NOT NULL CHECK (tier IN ('silver', 'gold', 'diamond')),
                    amount INTEGER NOT NULL CHECK (amount BETWEEN 1 AND 10000),
                    paid_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS bot_vip_memberships (
                    user_id BIGINT PRIMARY KEY,
                    tier TEXT NOT NULL CHECK (tier IN ('silver', 'gold', 'diamond')),
                    expires_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS bot_vip_memberships_expiry_idx
                    ON bot_vip_memberships (expires_at);
                CREATE TABLE IF NOT EXISTS bot_vip_profiles (
                    user_id BIGINT PRIMARY KEY,
                    display_name TEXT NOT NULL DEFAULT '',
                    custom_title TEXT NOT NULL DEFAULT '',
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                INSERT INTO schema_migrations (version, description)
                VALUES ('0004_vip_stars_one_time',
                        'One-time Telegram Stars VIP purchases and expiring profile perks')
                ON CONFLICT (version) DO NOTHING;
            """)


async def _active_membership(user_id: int):
    pool = database._require_pool()
    return await pool.fetchrow(
        """SELECT tier, expires_at FROM bot_vip_memberships
           WHERE user_id = $1 AND expires_at > NOW()""",
        user_id,
    )


async def _send_invoice(bot: Bot, chat_id: int, user_id: int, tier: str) -> None:
    amount = tier_price(tier)
    if amount is None:
        await bot.send_message(chat_id, "Покупка этого уровня сейчас недоступна.")
        return
    token = uuid.uuid4().hex
    payload = f"vip:{tier}:{token}"
    pool = database._require_pool()
    await pool.execute(
        """INSERT INTO bot_vip_invoice_intents
           (payload, user_id, tier, amount, expires_at)
           VALUES ($1, $2, $3, $4, NOW() + INTERVAL '20 minutes')""",
        payload, user_id, tier, amount,
    )
    details = TIERS[tier]
    try:
        await bot.send_invoice(
            chat_id=chat_id,
            title=details["name"],
            description=f"{details['name']} на 30 дней в VISE RUSSIA",
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{details['name']} · 30 дней", amount=amount)],
        )
    except Exception:
        await pool.execute(
            "DELETE FROM bot_vip_invoice_intents WHERE payload = $1 AND status = 'pending'",
            payload,
        )
        raise


async def vip_command(message: Message) -> None:
    if message.chat.type != "private":
        await message.answer("Откройте личный чат с ботом и отправьте /vip.")
        return
    await message.answer(
        build_shop_text(),
        parse_mode="HTML",
        reply_markup=vip_shop_keyboard(),
    )


async def vip_status_command(message: Message) -> None:
    if not message.from_user:
        return
    membership = await _active_membership(message.from_user.id)
    if membership is None:
        await message.answer("Активного VIP сейчас нет. Посмотреть уровни: /vip")
        return
    tier = str(membership["tier"])
    expiry = membership["expires_at"].astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")
    await message.answer(
        f"{TIERS[tier]['badge']} <b>{TIERS[tier]['name']}</b>\n"
        f"Действует до: <b>{expiry}</b>\n"
        "Автопродления нет. После окончания можно оформить новую покупку через /vip.",
        parse_mode="HTML",
    )


async def vip_perks_command(message: Message) -> None:
    await message.answer(build_shop_text(), parse_mode="HTML")


async def vip_profile_command(message: Message) -> None:
    if not message.from_user:
        return
    membership = await _active_membership(message.from_user.id)
    if membership is None:
        await message.answer("VIP-карточка доступна при активном VIP. Магазин: /vip")
        return
    pool = database._require_pool()
    profile = await pool.fetchrow(
        "SELECT display_name, custom_title FROM bot_vip_profiles WHERE user_id = $1",
        message.from_user.id,
    )
    tier = str(membership["tier"])
    display_name = (profile["display_name"] if profile else "") or message.from_user.full_name
    custom_title = (profile["custom_title"] if profile else "") or TIERS[tier]["name"]
    expiry = membership["expires_at"].astimezone(timezone.utc).strftime("%d.%m.%Y")
    await message.answer(
        f"{TIERS[tier]['badge']} <b>{escape(TIERS[tier]['name'])}</b>\n"
        f"Участник: <b>{escape(display_name)}</b>\n"
        f"Титул: {escape(custom_title)}\n"
        f"Действует до: {expiry}",
        parse_mode="HTML",
    )


async def vip_badge_command(message: Message) -> None:
    if not message.from_user:
        return
    membership = await _active_membership(message.from_user.id)
    if membership is None:
        await message.answer("Бейдж доступен при активном VIP. Магазин: /vip")
        return
    tier = str(membership["tier"])
    await message.answer(f"Ваш VIP-бейдж: {TIERS[tier]['badge']} {TIERS[tier]['name']}")


async def vip_name_command(message: Message) -> None:
    if not message.from_user:
        return
    membership = await _active_membership(message.from_user.id)
    if membership is None or TIER_ORDER[str(membership["tier"])] < TIER_ORDER["gold"]:
        await message.answer("Команда /vipname доступна с уровня VIP Gold. Магазин: /vip")
        return
    value = (message.text or "").partition(" ")[2].strip()
    if not 1 <= len(value) <= 24:
        await message.answer("Использование: /vipname Новое имя (до 24 символов).")
        return
    pool = database._require_pool()
    await pool.execute(
        """INSERT INTO bot_vip_profiles (user_id, display_name)
           VALUES ($1, $2)
           ON CONFLICT (user_id) DO UPDATE SET
             display_name = EXCLUDED.display_name, updated_at = NOW()""",
        message.from_user.id, value,
    )
    await message.answer("Отображаемое имя сохранено. Посмотреть карточку: /vipprofile")


async def vip_title_command(message: Message) -> None:
    if not message.from_user:
        return
    membership = await _active_membership(message.from_user.id)
    if membership is None or membership["tier"] != "diamond":
        await message.answer("Команда /viptitle доступна только с уровнем VIP Diamond. Магазин: /vip")
        return
    value = (message.text or "").partition(" ")[2].strip()
    if not 1 <= len(value) <= 32:
        await message.answer("Использование: /viptitle Ваш титул (до 32 символов).")
        return
    pool = database._require_pool()
    await pool.execute(
        """INSERT INTO bot_vip_profiles (user_id, custom_title)
           VALUES ($1, $2)
           ON CONFLICT (user_id) DO UPDATE SET
             custom_title = EXCLUDED.custom_title, updated_at = NOW()""",
        message.from_user.id, value,
    )
    await message.answer("Титул сохранён. Посмотреть карточку: /vipprofile")


async def vip_navigation_callback(callback: CallbackQuery) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[0] != "vip":
        await callback.answer("Неизвестное действие.", show_alert=True)
        return
    action, value = parts[1], parts[2]
    if action == "page":
        if value == "shop":
            await _edit_vip_screen(callback, build_shop_text(), vip_shop_keyboard())
        elif value == "compare":
            await _edit_vip_screen(callback, _compare_text(), _navigation_keyboard(value))
        elif value == "faq":
            await _edit_vip_screen(callback, _faq_text(), _navigation_keyboard(value))
        elif value == "status":
            body, keyboard = await _status_screen(callback.from_user.id)
            await _edit_vip_screen(callback, body, keyboard)
        else:
            await callback.answer("Раздел не найден.", show_alert=True)
        return
    if action == "detail" and value in TIERS:
        await _edit_vip_screen(callback, _detail_text(value), _detail_keyboard(value))
        return
    if action == "confirm" and value in TIERS:
        price = tier_price(value)
        if price is None:
            await callback.answer("Покупка сейчас недоступна.", show_alert=True)
            return
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Подтвердить · {price} ⭐",
                                  callback_data=f"vip:buy:{value}")],
            [InlineKeyboardButton(text="↩️ Назад", callback_data=f"vip:detail:{value}")],
        ])
        await _edit_vip_screen(
            callback,
            f"🧾 <b>Подтверждение покупки</b>\n\n"
            f"{TIERS[value]['badge']} <b>{TIERS[value]['name']}</b>\n"
            f"Стоимость: <b>{price} ⭐</b>\nСрок: <b>30 дней</b>\n"
            "Автопродления нет. Нажмите «Подтвердить», чтобы запросить счёт.",
            keyboard,
        )
        return
    if action == "buy" and value in TIERS:
        if not callback.message or callback.message.chat.type != "private":
            await callback.answer("Покупка доступна только в личном чате.", show_alert=True)
            return
        await callback.answer()
        await _send_invoice(callback.bot, callback.message.chat.id, callback.from_user.id, value)
        return
    await callback.answer("Неизвестное действие.", show_alert=True)


async def vip_pre_checkout(query: PreCheckoutQuery) -> None:
    pool = database._require_pool()
    row = await pool.fetchrow(
        """SELECT user_id, tier, amount FROM bot_vip_invoice_intents
           WHERE payload = $1 AND status = 'pending' AND expires_at > NOW()""",
        query.invoice_payload,
    )
    valid = bool(
        row
        and int(row["user_id"]) == query.from_user.id
        and query.currency == "XTR"
        and int(row["amount"]) == query.total_amount
        and row["tier"] in TIERS
    )
    if not valid:
        await query.answer(
            ok=False,
            error_message="Счёт устарел или не соответствует покупке. Откройте /vip и создайте новый.",
        )
        return
    await query.answer(ok=True)


async def vip_successful_payment(message: Message) -> None:
    if not message.from_user or not message.successful_payment:
        return
    payment = message.successful_payment
    if payment.currency != "XTR":
        await message.answer("Платёж не прошёл проверку валюты. Обратитесь в поддержку: /support")
        return

    pool = database._require_pool()
    activated_tier = None
    invalid_payment = False
    async with pool.acquire() as connection:
        async with connection.transaction():
            already_processed = await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM bot_vip_payments WHERE telegram_charge_id = $1)",
                payment.telegram_payment_charge_id,
            )
            if already_processed:
                return

            intent = await connection.fetchrow(
                """SELECT user_id, tier, amount, status
                   FROM bot_vip_invoice_intents WHERE payload = $1 FOR UPDATE""",
                payment.invoice_payload,
            )
            if (
                intent is None
                or int(intent["user_id"]) != message.from_user.id
                or intent["status"] != "pending"
                or int(intent["amount"]) != payment.total_amount
                or intent["tier"] not in TIERS
            ):
                invalid_payment = True
                LOGGER.error("VIP payment could not be matched to a pending invoice")
            else:
                inserted = await connection.fetchval(
                    """INSERT INTO bot_vip_payments
                       (telegram_charge_id, payload, user_id, tier, amount)
                       VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT DO NOTHING RETURNING telegram_charge_id""",
                    payment.telegram_payment_charge_id,
                    payment.invoice_payload,
                    message.from_user.id,
                    intent["tier"],
                    payment.total_amount,
                )
                if inserted:
                    await connection.execute(
                        """INSERT INTO bot_vip_memberships (user_id, tier, expires_at)
                           VALUES ($1, $2, NOW() + INTERVAL '30 days')
                           ON CONFLICT (user_id) DO UPDATE SET
                             tier = EXCLUDED.tier,
                             expires_at = GREATEST(bot_vip_memberships.expires_at, NOW())
                                          + INTERVAL '30 days',
                             updated_at = NOW()""",
                        message.from_user.id,
                        intent["tier"],
                    )
                    await connection.execute(
                        "UPDATE bot_vip_invoice_intents SET status = 'paid' WHERE payload = $1",
                        payment.invoice_payload,
                    )
                    activated_tier = str(intent["tier"])

    if invalid_payment:
        await message.answer(
            "Платёж получен, но его не удалось автоматически сопоставить с заказом. "
            "Обратитесь в поддержку: /support"
        )
        return
    if activated_tier is None:
        return
    await message.answer(
        f"✅ Оплата подтверждена. Активирован {TIERS[activated_tier]['badge']} "
        f"<b>{TIERS[activated_tier]['name']}</b> на 30 дней. Автопродления нет.\n"
        "Посмотреть срок: /vipstatus",
        parse_mode="HTML",
    )

async def pay_support_command(message: Message) -> None:
    await message.answer(
        "По вопросам оплаты Telegram Stars, возврата или неактивированного VIP "
        "обратитесь к команде поддержки через /support. Сохраните сообщение об оплате."
    )


def register_vip_handlers(dispatcher: Dispatcher) -> None:
    """Register VIP shop, profile perks and one-time Stars payment handlers."""
    dispatcher.message.register(vip_command, Command("vip"))
    dispatcher.message.register(vip_status_command, Command("vipstatus"))
    dispatcher.message.register(vip_perks_command, Command("vipperks"))
    dispatcher.message.register(vip_profile_command, Command("vipprofile"))
    dispatcher.message.register(vip_badge_command, Command("vipbadge"))
    dispatcher.message.register(vip_name_command, Command("vipname"))
    dispatcher.message.register(vip_title_command, Command("viptitle"))
    dispatcher.message.register(pay_support_command, Command("paysupport"))
    dispatcher.callback_query.register(vip_navigation_callback, F.data.startswith("vip:"))
    dispatcher.pre_checkout_query.register(vip_pre_checkout)
    dispatcher.message.register(vip_successful_payment, F.successful_payment)
