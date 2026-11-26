"""In-game phone, city directory and scheduled city events."""
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message


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
    ("Городская ярмарка", "Знакомство с городскими организациями и торговыми точками.", 14),
    ("День открытых дверей", "Презентации игровых фракций и профессий.", 38),
    ("Городской субботник", "Совместное общественное мероприятие игроков.", 62),
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
    for title, description, offset_hours in EVENTS:
        starts = current + timedelta(hours=offset_hours)
        lines.append(
            f"🎉 <b>{escape(title)}</b>\n{escape(description)}\n"
            f"🕒 Начало: <b>{starts.strftime('%d.%m.%Y %H:%M UTC')}</b>"
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
