"""In-game city transport routes, tickets and fictional passenger rides."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import Message

from database import database


def format_transport_routes(routes: list) -> str:
    lines = ["🚌 <b>Городские маршруты</b>"]
    for route in routes:
        lines.append(
            f"\n<b>{route['id']}. {escape(route['route_code'])} — {escape(route['name'])}</b>\n"
            f"Транспорт: {escape(route['vehicle_type'])} · "
            f"Интервал: {route['interval_minutes']} мин. · "
            f"Билет: {route['fare']} монет · Остановок: {route['stops']}"
        )
    if not routes:
        lines.append("Маршруты пока недоступны.")
    return "\n".join(lines)


def format_transport_stops(route_id: int, stops: list) -> str:
    lines = [f"🚏 <b>Остановки маршрута {route_id}</b>"]
    for stop in stops:
        lines.append(
            f"\n<b>{stop['stop_order']}.</b> {escape(stop['name'])} "
            f"— {escape(stop['district'])} (ID <code>{stop['id']}</code>)"
        )
    if not stops:
        lines.append("На этом маршруте нет остановок.")
    return "\n".join(lines)


def format_transport_history(history: list) -> str:
    lines = ["🧾 <b>Последние поездки</b>"]
    for ride in history:
        lines.append(
            f"\n{escape(ride['route_name'])}: "
            f"{escape(ride['from_name'])} → {escape(ride['to_name'])}"
        )
    if not history:
        lines.append("История поездок пока пуста.")
    return "\n".join(lines)


async def manage_transport(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    action = parts[0].lower() if parts else "help"
    user_id = message.from_user.id

    if action in {"routes", "route"} and len(parts) == 1:
        routes = await database.list_transport_routes()
        await message.answer(format_transport_routes(routes), parse_mode="HTML")
        return

    if action == "stops" and len(parts) == 2:
        try:
            route_id = int(parts[1])
            if route_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /bus stops ID_МАРШРУТА")
            return
        stops = await database.list_transport_stops(route_id)
        await message.answer(format_transport_stops(route_id, stops), parse_mode="HTML")
        return

    if action == "ticket" and len(parts) == 2:
        try:
            quantity = int(parts[1])
        except ValueError:
            quantity = 0
        username = (message.from_user.full_name or message.from_user.username or f"Игрок {user_id}")[:64]
        ok, result = await database.buy_transport_tickets(user_id, username, quantity)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "ride" and len(parts) == 4:
        try:
            route_id, from_id, to_id = map(int, parts[1:])
            if min(route_id, from_id, to_id) <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /bus ride ID_МАРШРУТА ID_ОСТАНОВКИ_ОТКУДА ID_ОСТАНОВКИ_КУДА")
            return
        ok, result = await database.ride_city_transport(user_id, route_id, from_id, to_id)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "tickets" and len(parts) == 1:
        count = await database.get_transport_ticket_count(user_id)
        await message.answer(f"🎫 У тебя билетов: <b>{count}</b>", parse_mode="HTML")
        return

    if action == "history" and len(parts) == 1:
        history = await database.get_transport_ride_history(user_id)
        await message.answer(format_transport_history(history), parse_mode="HTML")
        return

    await message.answer(
        "🚌 <b>Городской транспорт</b>\n"
        "/bus routes — маршруты\n"
        "/bus stops ID — остановки маршрута\n"
        "/bus ticket КОЛИЧЕСТВО — купить 1–10 билетов\n"
        "/bus tickets — остаток билетов\n"
        "/bus ride ROUTE_ID FROM_STOP_ID TO_STOP_ID — поездка\n"
        "/bus history — последние поездки",
        parse_mode="HTML",
    )
