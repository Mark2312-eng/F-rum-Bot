"""In-game phone, city directory and scheduled city events."""
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database


CITY_PLACES = [
    ("🏛 Мэрия", "Центральная площадь", "Городское управление и документы."),
    ("🏥 Больница", "Проспект Здоровья, 12", "Медицинские игровые услуги."),
    ("🚓 Полицейский участок", "Улица Порядка, 4", "Городская служба безопасности."),
    ("🔧 Автомастерская", "Промышленная улица, 8", "Обслуживание игрового транспорта."),
    ("🏦 Банк", "Финансовая улица, 1", "Игровые банковские сервисы."),
    ("🛒 Торговый центр", "Центральный район", "Магазины и городские услуги."),
]

CITY_ZONES = [
    ("Центр", "Мэрия, банк, торговый центр"),
    ("Северный район", "Жилые кварталы и парк"),
    ("Промзона", "Автомастерские и склады"),
    ("Южный район", "Больница и автовокзал"),
]

EVENTS = [
    ("Городская ярмарка", "Знакомство с городскими организациями и торговыми точками.", 14, "fair"),
    ("День открытых дверей", "Презентации игровых фракций и профессий.", 38, "open_day"),
    ("Городской субботник", "Совместное общественное мероприятие игроков.", 62, "cleanup"),
]


def phone_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗺 Карта города", callback_data="phone:city")],
        [InlineKeyboardButton(text="📍 Организации и места", callback_data="phone:places")],
        [InlineKeyboardButton(text="📅 События", callback_data="phone:events")],
    ])


def format_city() -> str:
    lines = ["🗺 <b>Карта игрового города</b>", ""]
    for zone, details in CITY_ZONES:
        lines.append(f"📌 <b>{escape(zone)}</b>\n{escape(details)}")
    lines.append("\nИспользуй раздел «Организации и места», чтобы посмотреть адреса.")
    return "\n\n".join(lines)


def format_places() -> str:
    lines = ["📍 <b>Телефонный справочник города</b>", ""]
    for name, address, description in CITY_PLACES:
        lines.append(f"{name}\n📌 {escape(address)}\n{escape(description)}")
    return "\n\n".join(lines)


def format_events(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    lines = ["📅 <b>Городские события</b>", ""]
    for title, description, offset_hours, code in EVENTS:
        starts = current + timedelta(hours=offset_hours)
        lines.append(
            f"🎉 <b>{escape(title)}</b>\n{escape(description)}\n"
            f"🕒 Начало: <b>{starts.strftime('%d.%m.%Y %H:%M UTC')}</b>\\nКод записи: <code>{code}</code>"
        )
    lines.append("\nВремя указано по UTC. Это игровые события, не реальные мероприятия.")
    return "\n\n".join(lines)


async def show_phone(message: Message) -> None:
    await message.answer(
        "📱 <b>Игровой телефон</b>\n\nВыбери нужное приложение:",
        parse_mode="HTML", reply_markup=phone_keyboard(),
    )


async def show_city(message: Message) -> None:
    await message.answer(format_city(), parse_mode="HTML")


async def show_places(message: Message) -> None:
    await message.answer(format_places(), parse_mode="HTML")


async def show_events(message: Message) -> None:
    await message.answer(format_events(), parse_mode="HTML")


async def handle_phone_callback(callback) -> None:
    if not callback.data or callback.message is None:
        await callback.answer()
        return
    screens = {
        "phone:city": format_city,
        "phone:places": format_places,
        "phone:events": format_events,
    }
    renderer = screens.get(callback.data)
    if renderer is None:
        await callback.answer()
        return
    await callback.message.answer(renderer(), parse_mode="HTML")
    await callback.answer()



async def manage_city_event(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    if not parts:
        await message.answer(
            "Команды событий:\n"
            "<code>/event join fair</code> — записаться\n"
            "<code>/event leave fair</code> — отменить запись\n"
            "<code>/event mine</code> — мои записи\n"
            "<code>/event list fair</code> — список участников",
            parse_mode="HTML",
        )
        return
    action = parts[0].lower()
    user_id = message.from_user.id
    username = (message.from_user.full_name or message.from_user.username or f"Игрок {user_id}")[:64]
    if action == "join" and len(parts) == 2:
        result = await database.signup_city_event(user_id, username, parts[1].lower())
        responses = {
            "joined": "✅ Запись на событие подтверждена.",
            "already": "ℹ️ Ты уже записан на это событие.",
            "missing": "⚠️ Неизвестный код события. Посмотри /events.",
        }
        await message.answer(responses[result])
    elif action == "leave" and len(parts) == 2:
        result = await database.leave_city_event(user_id, parts[1].lower())
        responses = {
            "left": "Запись отменена.",
            "not_joined": "Ты не записан на это событие.",
            "missing": "Неизвестный код события.",
        }
        await message.answer(responses[result])
    elif action == "mine" and len(parts) == 1:
        rows = await database.get_user_city_event_signups(user_id)
        labels = {code: title for title, _, _, code in EVENTS}
        if not rows:
            await message.answer("У тебя пока нет записей на события.")
        else:
            await message.answer(
                "📅 <b>Мои записи</b>\n" + "\n".join(
                    f"• {escape(labels[row['event_code']])}" for row in rows
                ),
                parse_mode="HTML",
            )
    elif action == "list" and len(parts) == 2:
        code = parts[1].lower()
        rows = await database.get_city_event_signups(code)
        labels = {event_code: title for title, _, _, event_code in EVENTS}
        if code not in labels:
            await message.answer("Неизвестный код события.")
        else:
            lines = [f"👥 <b>{escape(labels[code])}: участники</b>"]
            lines.extend(
                f"• {escape(row['username'] or ('Игрок ' + str(row['user_id'])))}"
                for row in rows
            )
            await message.answer("\n".join(lines), parse_mode="HTML")
    else:
        await message.answer("Формат: /event join|leave|mine|list КОД")
