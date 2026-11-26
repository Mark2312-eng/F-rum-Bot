"""In-game medical organizations and fictional patient-NPC activities."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import Message

from database import database


def format_medical_centers(centers: list) -> str:
    lines = ["🏥 <b>Медицинские организации города</b>"]
    for center in centers:
        lines.append(
            f"\n<b>{center['id']}. {escape(center['name'])}</b>\n"
            f"Район: {escape(center['district'])} · Сотрудников: {center['employees']}"
        )
    if not centers:
        lines.append("Медицинские организации пока не созданы.")
    return "\n".join(lines)


def format_medical_profile(profile) -> str:
    if profile is None:
        return (
            "🪪 <b>Медицинская карточка</b>\n"
            "Ты пока не работаешь в больнице.\n"
            "Сначала вступи во фракцию «Городская больница», затем используй /med apply ID."
        )
    return (
        "🪪 <b>Медицинская карточка</b>\n"
        f"Организация: <b>{escape(profile['center_name'])}</b>\n"
        f"Район: <b>{escape(profile['district'])}</b>\n"
        f"Должность: <b>{escape(profile['job_title'])}</b>\n"
        f"Руководитель фракции ID: <code>{profile['leader_id'] or 'не назначен'}</code>"
    )


def format_medical_missions(missions: list) -> str:
    lines = ["📋 <b>Игровые медицинские задания</b>"]
    for mission in missions:
        status = "уже выполнено сегодня" if mission["completed_today"] else "доступно"
        lines.append(
            f"\n<code>{escape(mission['code'])}</code> — {escape(mission['title'])}\n"
            f"Награда: {mission['reward_coins']} монет, {mission['reward_xp']} XP · {status}"
        )
    if not missions:
        lines.append("Задания недоступны. Сначала устройся в медицинскую организацию.")
    return "\n".join(lines)


def format_medical_roster(center, members: list) -> str:
    lines = [f"👥 <b>{escape(center['faction_name'])} — состав</b>"]
    for member in members:
        name = member["username"] or f"Игрок {member['user_id']}"
        lines.append(
            f"• {escape(name)} — {escape(member['job_title'])}; "
            f"{escape(member['center_name'])} (ID <code>{member['user_id']}</code>)"
        )
    if not members:
        lines.append("Сотрудников пока нет.")
    return "\n".join(lines)


async def manage_medical(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    action = parts[0].lower() if parts else "profile"
    user_id = message.from_user.id
    username = (message.from_user.full_name or message.from_user.username or f"Игрок {user_id}")[:64]

    if action in {"profile", "info"} and len(parts) == 1:
        profile = await database.get_medical_profile(user_id)
        await message.answer(format_medical_profile(profile), parse_mode="HTML")
        return

    if action == "centers" and len(parts) == 1:
        centers = await database.list_medical_centers()
        await message.answer(format_medical_centers(centers), parse_mode="HTML")
        return

    if action == "apply" and len(parts) == 2:
        try:
            center_id = int(parts[1])
            if center_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /med apply ID_ЦЕНТРА")
            return
        ok, result = await database.apply_medical_center(user_id, username, center_id)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "leave" and len(parts) == 1:
        ok = await database.leave_medical_center(user_id)
        await message.answer(
            "Ты уволен из медицинской организации. Членство во фракции сохранено."
            if ok else "Ты не работаешь в медицинской организации."
        )
        return

    if action == "tasks" and len(parts) == 1:
        missions = await database.list_medical_missions(user_id)
        await message.answer(format_medical_missions(missions), parse_mode="HTML")
        return

    if action == "complete" and len(parts) == 2:
        code = parts[1].lower()
        if len(code) > 32 or not code.replace("_", "").isalnum():
            await message.answer("Укажи код задания из списка /med tasks.")
            return
        ok, result = await database.complete_medical_mission(user_id, code)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action in {"promote", "demote"} and len(parts) == 2:
        try:
            target_id = int(parts[1])
            if target_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /med promote ID или /med demote ID")
            return
        direction = 1 if action == "promote" else -1
        ok, result = await database.change_medical_job_title(user_id, target_id, direction)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "members" and len(parts) == 1:
        center, members = await database.get_medical_roster(user_id)
        if center is None:
            await message.answer("Сначала устройся через /med apply ID.")
            return
        await message.answer(format_medical_roster(center, members), parse_mode="HTML")
        return

    await message.answer(
        "Команды: /med, /med centers, /med apply ID, /med leave, "
        "/med tasks, /med complete CODE, /med members, "
        "/med promote ID, /med demote ID"
    )
