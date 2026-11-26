"""In-game schools, university, lessons and fictional exams."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import Message

from database import database


def format_education_institutions(institutions: list) -> str:
    lines = ["🎓 <b>Учебные заведения города</b>"]
    for item in institutions:
        lines.append(
            f"\n<b>{item['id']}. {escape(item['name'])}</b>\n"
            f"Тип: {escape(item['institution_type'])} · Район: {escape(item['district'])}\n"
            f"Учащихся: {item['students']}"
        )
    if not institutions:
        lines.append("Учебные заведения пока не созданы.")
    return "\n".join(lines)


def format_education_groups(groups: list) -> str:
    lines = ["👥 <b>Учебные группы</b>"]
    for group in groups:
        lines.append(
            f"\n<b>{escape(group['institution_name'])}</b>\n"
            f"{escape(group['group_code'])} — {escape(group['group_name'])}\n"
            f"Учащихся: {group['students']}"
        )
    if not groups:
        lines.append("Учебные группы не найдены.")
    return "\n".join(lines)


def format_education_profile(profile) -> str:
    if profile is None:
        return (
            "📚 <b>Студенческий профиль</b>\n"
            "Ты пока не зачислен.\n"
            "Вступи во фракцию «Городское образование» и используй /edu enroll ID."
        )
    return (
        "📚 <b>Студенческий профиль</b>\n"
        f"Учебное заведение: <b>{escape(profile['institution_name'])}</b>\n"
        f"Тип: <b>{escape(profile['institution_type'])}</b>\n"
        f"Район: <b>{escape(profile['district'])}</b>\n"
        f"Telegram ID: <code>{profile['user_id']}</code>"
    )


def format_education_courses(courses: list) -> str:
    lines = ["📝 <b>Занятия и экзамены</b>"]
    for course in courses:
        kind = "Занятие" if course["course_type"] == "lesson" else "Экзамен"
        status = "засчитано сегодня" if course["completed_today"] else "доступно"
        lines.append(
            f"\n<b>{kind}</b> · <code>{escape(course['code'])}</code>\n"
            f"{escape(course['title'])}\n"
            f"Награда: {course['reward_coins']} монет, {course['reward_xp']} XP · {status}"
        )
    if not courses:
        lines.append("Сначала поступи в учебное заведение через /edu enroll ID.")
    return "\n".join(lines)


def format_education_roster(institution, students: list) -> str:
    lines = [f"👥 <b>{escape(institution['name'])} — список учащихся</b>"]
    for student in students:
        name = student["username"] or f"Игрок {student['user_id']}"
        lines.append(f"• {escape(name)} · ID <code>{student['user_id']}</code>")
    if not students:
        lines.append("Учащихся пока нет.")
    return "\n".join(lines)


async def manage_education(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split()
    action = parts[0].lower() if parts else "profile"
    user_id = message.from_user.id
    username = (message.from_user.full_name or message.from_user.username or f"Игрок {user_id}")[:64]

    if action in {"profile", "info"} and len(parts) == 1:
        profile = await database.get_education_profile(user_id)
        await message.answer(format_education_profile(profile), parse_mode="HTML")
        return

    if action in {"institutions", "schools"} and len(parts) == 1:
        institutions = await database.list_education_institutions()
        await message.answer(format_education_institutions(institutions), parse_mode="HTML")
        return

    if action == "groups" and len(parts) in (1, 2):
        institution_id = None
        if len(parts) == 2:
            try:
                institution_id = int(parts[1])
                if institution_id <= 0:
                    raise ValueError
            except ValueError:
                await message.answer("Формат: /edu groups [ID_УЧЕБНОГО_ЗАВЕДЕНИЯ]")
                return
        groups = await database.list_education_groups(institution_id)
        await message.answer(format_education_groups(groups), parse_mode="HTML")
        return

    if action == "enroll" and len(parts) == 2:
        try:
            institution_id = int(parts[1])
            if institution_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /edu enroll ID_УЧЕБНОГО_ЗАВЕДЕНИЯ")
            return
        ok, result = await database.enroll_education_student(user_id, username, institution_id)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "leave" and len(parts) == 1:
        ok = await database.leave_education_institution(user_id)
        await message.answer(
            "Ты отчислен. Членство во фракции «Городское образование» сохранено."
            if ok else "Ты не зачислен в учебное заведение."
        )
        return

    if action in {"classes", "courses"} and len(parts) == 1:
        courses = await database.list_education_courses(user_id)
        await message.answer(format_education_courses(courses), parse_mode="HTML")
        return

    if action in {"attend", "exam"} and len(parts) == 2:
        code = parts[1].lower()
        if len(code) > 32 or not code.replace("_", "").isalnum():
            await message.answer("Укажи код из списка /edu classes.")
            return
        course_type = "lesson" if action == "attend" else "exam"
        ok, result = await database.complete_education_course(user_id, code, course_type)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "roster" and len(parts) == 1:
        institution, students = await database.get_education_roster(user_id)
        if institution is None:
            await message.answer("Сначала поступи через /edu enroll ID.")
            return
        await message.answer(format_education_roster(institution, students), parse_mode="HTML")
        return

    await message.answer(
        "Команды: /edu, /edu institutions, /edu groups [ID], /edu enroll ID, /edu leave, "
        "/edu classes, /edu attend CODE, /edu exam CODE, /edu roster"
    )
