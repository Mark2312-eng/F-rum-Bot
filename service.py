"""In-game МВД and FSB career commands."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import Message

from database import database


def format_service_profile(profile) -> str:
    if profile is None:
        return (
            "🪪 <b>Служебная карточка</b>\n"
            "Ты пока не состоишь на службе.\n"
            "Используй <code>/service apply МВД</code> или <code>/service apply ФСБ</code>."
        )
    return (
        "🪪 <b>Служебная карточка</b>\n"
        f"Организация: <b>{escape(profile['faction_name'])}</b>\n"
        f"Звание: <b>{escape(profile['service_rank'])}</b>\n"
        f"Руководитель фракции ID: <code>{profile['leader_id'] or 'не назначен'}</code>"
    )


def format_service_missions(missions: list) -> str:
    lines = ["📋 <b>Учебные и городские задания</b>"]
    for mission in missions:
        status = "уже выполнено сегодня" if mission["completed_today"] else "доступно"
        lines.append(
            f"\n<code>{escape(mission['code'])}</code> — {escape(mission['title'])}\n"
            f"Награда: {mission['reward_coins']} монет, {mission['reward_xp']} XP · {status}"
        )
    if not missions:
        lines.append("Список заданий недоступен. Сначала оформи служебную карточку.")
    return "\n".join(lines)


def format_service_roster(faction, members: list) -> str:
    lines = [f"👥 <b>{escape(faction['name'])} — служебный состав</b>"]
    for member in members:
        name = member["username"] or f"Игрок {member['user_id']}"
        lines.append(
            f"• {escape(name)} — {escape(member['service_rank'])} "
            f"(ID <code>{member['user_id']}</code>)"
        )
    if not members:
        lines.append("Служебный состав пока пуст.")
    return "\n".join(lines)


async def manage_service(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    action = parts[0].lower() if parts else "profile"
    user_id = message.from_user.id

    if action in {"profile", "info"} and len(parts) == 1:
        profile = await database.get_game_service_profile(user_id)
        await message.answer(format_service_profile(profile), parse_mode="HTML")
        return

    if action == "apply" and len(parts) == 2:
        faction_name = parts[1].upper()
        ok, result = await database.apply_game_service(user_id, faction_name)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "leave" and len(parts) == 1:
        ok = await database.leave_game_service(user_id)
        await message.answer(
            "Служебная карточка закрыта. Членство во фракции сохранено."
            if ok else "У тебя нет активной служебной карточки."
        )
        return

    if action == "tasks" and len(parts) == 1:
        missions = await database.list_game_service_missions(user_id)
        await message.answer(format_service_missions(missions), parse_mode="HTML")
        return

    if action == "complete" and len(parts) == 2:
        code = parts[1].lower()
        if len(code) > 32 or not code.replace("_", "").isalnum():
            await message.answer("Укажи код задания из списка /service tasks.")
            return
        ok, result = await database.complete_game_service_mission(user_id, code)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action in {"promote", "demote"} and len(parts) == 2:
        try:
            target_id = int(parts[1])
            if target_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /service promote ID или /service demote ID")
            return
        direction = 1 if action == "promote" else -1
        ok, result = await database.change_game_service_rank(user_id, target_id, direction)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "members" and len(parts) == 1:
        faction, members = await database.get_game_service_roster(user_id)
        if faction is None:
            await message.answer("Сначала оформи служебную карточку через /service apply МВД или /service apply ФСБ.")
            return
        await message.answer(format_service_roster(faction, members), parse_mode="HTML")
        return

    await message.answer(
        "Команды: /service, /service apply МВД|ФСБ, /service leave, "
        "/service tasks, /service complete CODE, /service members, "
        "/service promote ID, /service demote ID"
    )
