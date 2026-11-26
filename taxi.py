"""In-game taxi dispatch, fictional rides and passenger ratings."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import Message

from database import database


def format_taxi_orders(orders: list) -> str:
    lines = ["🚕 <b>Свободные заказы такси</b>"]
    for order in orders:
        lines.append(
            f"\n<b>Заказ №{order['id']}</b> · {escape(order['route_name'])}\n"
            f"Пассажир: {escape(order['passenger_name'] or 'Игрок')}\n"
            f"{escape(order['from_name'])} → {escape(order['to_name'])}\n"
            f"Оплата: <b>{order['fare']} монет</b>"
        )
    if not orders:
        lines.append("Свободных заказов сейчас нет.")
    return "\n".join(lines)


def format_taxi_history(history: list) -> str:
    status_names = {
        "open": "Ожидает водителя",
        "accepted": "Принят водителем",
        "completed": "Завершён",
        "cancelled": "Отменён",
    }
    lines = ["🧾 <b>История такси</b>"]
    for order in history:
        lines.append(
            f"\n<b>Заказ №{order['id']}</b> · {escape(status_names.get(order['status'], 'Неизвестно'))}\n"
            f"{escape(order['route_name'])}: {escape(order['from_name'])} → "
            f"{escape(order['to_name'])}\n"
            f"Стоимость: {order['fare']} монет"
        )
        if order["driver_name"]:
            lines.append(f"Водитель: {escape(order['driver_name'])}")
    if not history:
        lines.append("История поездок пока пуста.")
    return "\n".join(lines)


def format_taxi_rating(rating) -> str:
    if rating is None or not rating["ratings"]:
        return "⭐ <b>Рейтинг водителя</b>\nПока нет оценок."
    average = rating["average_rating"]
    return (
        "⭐ <b>Рейтинг водителя</b>\n"
        f"Средняя оценка: <b>{average:.2f}/5</b>\n"
        f"Количество оценок: <b>{rating['ratings']}</b>"
    )


async def manage_taxi(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    action = parts[0].lower() if parts else "help"
    user_id = message.from_user.id

    if action == "orders" and len(parts) == 1:
        orders = await database.list_open_taxi_orders()
        await message.answer(format_taxi_orders(orders), parse_mode="HTML")
        return

    if action == "order" and len(parts) == 4:
        try:
            route_id, from_id, to_id = map(int, parts[1:])
            if min(route_id, from_id, to_id) <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /taxi order ROUTE_ID FROM_STOP_ID TO_STOP_ID")
            return
        username = (message.from_user.full_name or message.from_user.username or f"Игрок {user_id}")[:64]
        ok, result = await database.create_taxi_order(
            user_id, username, route_id, from_id, to_id
        )
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action in {"accept", "finish", "cancel"} and len(parts) == 2:
        try:
            order_id = int(parts[1])
            if order_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Укажи положительный ID заказа.")
            return
        if action == "accept":
            ok, result = await database.accept_taxi_order(user_id, order_id)
        elif action == "finish":
            ok, result = await database.finish_taxi_order(user_id, order_id)
        else:
            ok, result = await database.cancel_taxi_order(user_id, order_id)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "rate" and len(parts) == 3:
        try:
            order_id, rating = map(int, parts[1:])
            if order_id <= 0 or not 1 <= rating <= 5:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /taxi rate ID_ЗАКАЗА ОЦЕНКА_1_5")
            return
        ok, result = await database.rate_taxi_driver(user_id, order_id, rating)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "rating" and len(parts) == 1:
        rating = await database.get_taxi_driver_rating(user_id)
        await message.answer(format_taxi_rating(rating), parse_mode="HTML")
        return

    if action == "history" and len(parts) == 1:
        history = await database.get_taxi_history(user_id)
        await message.answer(format_taxi_history(history), parse_mode="HTML")
        return

    await message.answer(
        "🚕 <b>Городское такси</b>\n"
        "/taxi order ROUTE_ID FROM_STOP_ID TO_STOP_ID — вызвать такси\n"
        "/taxi orders — свободные заказы (для водителей)\n"
        "/taxi accept ID — принять заказ (работа «Таксист»)\n"
        "/taxi finish ID — завершить игровую поездку\n"
        "/taxi cancel ID — отменить непринятый заказ\n"
        "/taxi rate ID 1-5 — оценить водителя\n"
        "/taxi rating — рейтинг водителя\n"
        "/taxi history — история заказов",
        parse_mode="HTML",
    )
