"""In-game government departments, payroll and service assignments."""
from html import escape

from aiogram.filters import CommandObject
from aiogram.types import Message

from database import database


async def manage_government(message: Message, command: CommandObject) -> None:
    if not message.from_user:
        return
    parts = (command.args or "").split(maxsplit=3)
    action = parts[0].lower() if parts else "help"
    user_id = message.from_user.id
    username = (message.from_user.full_name or message.from_user.username or f"Игрок {user_id}")[:64]

    if action in {"help", "info"}:
        employee = await database.get_government_employee(user_id)
        lines = ["🏛 <b>Государственная служба</b>"]
        if employee:
            lines.extend([
                f"Отдел: <b>{escape(employee['department_name'])}</b>",
                f"Должность: <b>{escape(employee['position'])}</b>",
            ])
        else:
            lines.append("Ты пока не работаешь в государственном отделе.")
        lines.extend([
            "",
            "<code>/gov departments</code> — список отделов",
            "<code>/gov join ID</code> — устроиться в отдел",
            "<code>/gov leave</code> — уволиться",
            "<code>/gov salary</code> — получить зарплату (раз в 24 часа)",
            "<code>/gov tasks</code> — мои поручения",
            "<code>/gov complete ID</code> — выполнить поручение",
            "<code>/gov roster ID</code> — состав отдела",
            "<code>/gov assign ID НАГРАДА ТЕКСТ</code> — поручение сотруднику",
            "<code>/gov appoint ID СОТРУДНИКА</code> — назначить начальника отдела",
        ])
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    if action == "departments" and len(parts) == 1:
        departments = await database.list_government_departments()
        lines = ["🏢 <b>Государственные отделы</b>"]
        for item in departments:
            lines.append(
                f"\n<b>{item['id']}. {escape(item['name'])}</b>\n"
                f"{escape(item['description'])}\n"
                f"Сотрудников: {item['employees']} · Базовая зарплата: {item['base_salary']}"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    if action in {"join", "roster"} and len(parts) == 2:
        try:
            department_id = int(parts[1])
            if department_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Укажи корректный ID отдела.")
            return
        if action == "join":
            ok, result = await database.join_government_department(user_id, username, department_id)
            await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        else:
            departments = await database.list_government_departments()
            selected = next((d for d in departments if d["id"] == department_id), None)
            if selected is None:
                await message.answer("Отдел не найден.")
                return
            members = await database.get_government_roster(department_id)
            lines = [f"👥 <b>{escape(selected['name'])}</b>"]
            lines.extend(
                f"• {escape(row['username'] or ('Игрок ' + str(row['user_id'])))} — "
                f"{escape(row['position'])} (ID <code>{row['user_id']}</code>)"
                for row in members
            )
            if not members:
                lines.append("В отделе пока нет сотрудников.")
            await message.answer("\n".join(lines), parse_mode="HTML")
        return

    if action == "leave" and len(parts) == 1:
        ok = await database.leave_government_department(user_id)
        await message.answer("Ты уволен из государственного отдела." if ok else "Ты не работаешь в государственном отделе.")
        return

    if action == "salary" and len(parts) == 1:
        ok, result = await database.claim_government_salary(user_id)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "tasks" and len(parts) == 1:
        tasks = await database.get_government_tasks(user_id)
        lines = ["📋 <b>Мои служебные поручения</b>"]
        lines.extend(
            f"№{task['id']} · {escape(task['title'])} · {task['reward_coins']} монет · "
            f"{'выполнено' if task['status'] == 'completed' else 'открыто'}"
            for task in tasks
        )
        if not tasks:
            lines.append("Поручений пока нет.")
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    if action == "complete" and len(parts) == 2:
        try:
            task_id = int(parts[1])
            if task_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Укажи корректный номер поручения.")
            return
        ok, result = await database.complete_government_task(user_id, task_id)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "appoint" and len(parts) == 3:
        try:
            department_id = int(parts[1])
            target_id = int(parts[2])
            if department_id <= 0 or target_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /gov appoint ID_ОТДЕЛА ID_СОТРУДНИКА")
            return
        ok, result = await database.appoint_government_head(user_id, target_id, department_id)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    if action == "assign" and len(parts) == 4:
        try:
            target_id = int(parts[1])
            reward = int(parts[2])
            if target_id <= 0:
                raise ValueError
        except ValueError:
            await message.answer("Формат: /gov assign ID_СОТРУДНИКА НАГРАДА ТЕКСТ")
            return
        ok, result = await database.assign_government_task(user_id, target_id, parts[3], reward)
        await message.answer(("✅ " if ok else "⚠️ ") + escape(result), parse_mode="HTML")
        return

    await message.answer("Неизвестная команда. Используй /gov для справки.")
