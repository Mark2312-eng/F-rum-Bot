"""Virtual shop, inventory, property and vehicle garage."""
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import database
from game import display_name


def catalog_keyboard(items: list, kind: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"🛒 {item['name']} · {item['price']} монет",
            callback_data=f"eco:buy:{kind}:{item['code']}",
        )]
        for item in items
    ]
    rows.append([InlineKeyboardButton(text="🎒 Инвентарь", callback_data="eco:inventory")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def format_catalog(items: list, title: str) -> str:
    if not items:
        return f"{title}\n\nПока ничего нет в продаже."
    lines = [title, ""]
    for item in items:
        lines.append(
            f"📦 <b>{escape(item['name'])}</b> — <b>{item['price']}</b> монет\n"
            f"{escape(item['description'])}"
        )
    lines.append("\nПокупки оплачиваются только виртуальными игровыми монетами.")
    return "\n\n".join(lines)


def format_inventory(items: list) -> str:
    lines = ["🎒 <b>Инвентарь</b>", ""]
    if not items:
        lines.append("Инвентарь пуст.")
    else:
        for item in items:
            name = item["name"] or item["item_code"]
            lines.append(f"📦 {escape(name)} × <b>{item['quantity']}</b>")
            if item["description"]:
                lines.append(escape(item["description"]))
    return "\n".join(lines)


async def show_shop(message: Message) -> None:
    items = await database.get_game_shop_items()
    await message.answer(
        format_catalog(items, "🛍 <b>Игровой магазин</b>"),
        parse_mode="HTML", reply_markup=catalog_keyboard(items, "item"),
    )


async def show_inventory(message: Message) -> None:
    if not message.from_user:
        return
    items = await database.get_game_inventory(message.from_user.id)
    await message.answer(format_inventory(items), parse_mode="HTML")


async def show_properties(message: Message) -> None:
    if not message.from_user:
        return
    owned = await database.get_game_property(message.from_user.id)
    if owned:
        text = (
            f"🏠 <b>Твоя недвижимость: {escape(owned['name'])}</b>\n"
            f"Тип: {escape(owned['property_type'])}\n"
            f"ID объекта: <code>{owned['id']}</code>"
        )
        await message.answer(text, parse_mode="HTML")
        return
    items = await database.get_game_property_catalog()
    await message.answer(
        format_catalog(items, "🏠 <b>Недвижимость</b>\n\nУ тебя пока нет жилья."),
        parse_mode="HTML", reply_markup=catalog_keyboard(items, "property"),
    )


async def show_garage(message: Message) -> None:
    if not message.from_user:
        return
    vehicles = await database.get_game_vehicles(message.from_user.id)
    if vehicles:
        lines = ["🚘 <b>Твой гараж</b>", ""]
        for vehicle in vehicles:
            lines.append(f"🚗 <b>{escape(vehicle['name'])}</b> · ID {vehicle['id']}")
            lines.append(escape(vehicle["description"]))
        await message.answer("\n".join(lines), parse_mode="HTML")
        return
    items = await database.get_game_vehicle_catalog()
    await message.answer(
        format_catalog(items, "🚘 <b>Автосалон</b>\n\nВ гараже пока нет транспорта."),
        parse_mode="HTML", reply_markup=catalog_keyboard(items, "vehicle"),
    )


async def handle_economy_callback(callback) -> None:
    if callback.message is None or callback.from_user is None or not callback.data:
        await callback.answer()
        return
    data = callback.data
    user_id = callback.from_user.id
    if data == "eco:inventory":
        items = await database.get_game_inventory(user_id)
        await callback.message.answer(format_inventory(items), parse_mode="HTML")
        await callback.answer()
        return
    parts = data.split(":")
    if len(parts) != 4 or parts[:2] != ["eco", "buy"]:
        await callback.answer()
        return
    _, _, kind, code = parts
    username = display_name(callback.from_user)
    if kind == "item":
        status, price = await database.buy_game_item(user_id, username, code)
        success_text = f"Покупка выполнена: списано {price} монет."
    elif kind == "property":
        status, price = await database.buy_game_property(user_id, username, code)
        success_text = f"Недвижимость приобретена за {price} монет."
    elif kind == "vehicle":
        status, price = await database.buy_game_vehicle(user_id, username, code)
        success_text = f"Транспорт приобретён за {price} монет."
    else:
        await callback.answer("Неизвестный раздел.", show_alert=True)
        return
    if status == "ok":
        await callback.answer("Покупка успешна.")
        await callback.message.answer("✅ " + success_text)
    elif status == "funds":
        await callback.answer(f"Недостаточно монет. Цена: {price}.", show_alert=True)
    elif status == "owned":
        await callback.answer("У тебя уже есть недвижимость.", show_alert=True)
    elif status == "limit":
        await callback.answer("В гараже можно хранить не более 3 машин.", show_alert=True)
    else:
        await callback.answer("Этот товар больше недоступен.", show_alert=True)
